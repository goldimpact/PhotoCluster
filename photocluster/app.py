import csv
import io
import re
import hashlib
import threading
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, StrictBool
from PIL import Image, ImageOps

from . import adb
from .service import ROOT, Service
from .operations import Operations
from .video import VideoLeases
from .runtime import Runtime, AdmissionMiddleware
from .cache import CacheManager, summary as cache_summary

@asynccontextmanager
async def lifespan(app):
    yield
    for token in list(video_leases.items):
        video_leases.release(token)


app = FastAPI(title='PhotoCluster', lifespan=lifespan)
app.state.runtime = Runtime()
app.add_middleware(AdmissionMiddleware, owner=app)
service = Service()
operations = Operations(service)
cache_manager = CacheManager(service, operations)
original_slots = threading.BoundedSemaphore(2)
video_leases=VideoLeases()


@app.get('/api/runtime')
def runtime_status():
    return JSONResponse(app.state.runtime.snapshot(), headers={'Cache-Control': 'no-store'})


@app.post('/api/runtime/exit')
def runtime_exit(request: Request):
    runtime = app.state.runtime
    if not secrets.compare_digest(request.headers.get('X-PhotoCluster-Token', ''), runtime.token):
        raise HTTPException(403, 'Invalid lifecycle token')
    if not runtime.managed:
        raise HTTPException(409, 'This instance is managed by an external command.')
    runtime.request_exit()
    service.cancel.set()
    return {'stopping': True}


@app.middleware('http')
async def local_requests(request: Request, call_next):
    if request.headers.get('host', '').split(':')[0] not in ('127.0.0.1', 'localhost', 'testserver'):
        return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        return JSONResponse({'detail': '不允许跨站请求'}, status_code=403)
    response=await call_next(request)
    if request.url.path in ('/','/index.html') or request.url.path.endswith(('.js','.css')):
        response.headers['Cache-Control']='no-cache'
    return response


@app.get('/api/devices')
def devices():
    try:
        return adb.devices()
    except Exception as exc:
        raise HTTPException(503, str(exc))


class Refresh(BaseModel):
    serial: str = Field(min_length=1, max_length=200)


@app.post('/api/refresh')
def refresh(body: Refresh):
    try:
        return service.refresh(body.serial)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(503, str(exc))


@app.get('/api/albums')
def albums():
    return service.albums()


@app.get('/api/sync-status')
def sync_status():
    with service.lock:return dict(service.sync_status)


class VariantRules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mirror: StrictBool = True
    perspective: StrictBool = True
    warp: StrictBool = False


class Scan(BaseModel):
    albums: list[str]
    mode: Literal['strict', 'strong', 'relaxed','content','variants','subject'] = 'variants'
    scope: Literal['all', 'album'] = 'all'
    limit: int = Field(default=0, ge=0)
    force: bool = False
    all_albums: bool = False
    serial: str | None = None
    threshold: float = Field(default=.84,ge=.65,le=.98)
    rules: VariantRules = Field(default_factory=VariantRules)
    subject_engine: Literal['auto','general','anime'] = 'auto'


@app.post('/api/scan')
def scan(body: Scan):
    try:
        return service.start(body.albums, body.mode, body.scope, body.limit, body.force, body.all_albums, body.serial,body.threshold,body.rules.model_dump(),subject_engine=body.subject_engine)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post('/api/stop')
def stop():
    service.cancel.set()
    return {'message': '停止请求已收到，正在完成当前读取'}


@app.get('/api/status')
def status():
    with service.lock:
        return dict(service.status)


@app.get('/api/hardware')
def hardware():
    from .acceleration import hardware_info,cuda
    cuda()
    return hardware_info()


class CacheScope(BaseModel):
    scope: Literal['results', 'analysis', 'all']


class CacheToken(BaseModel):
    token: str


@app.get('/api/cache')
def cache_status():
    try:
        return cache_summary(service)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post('/api/cache/preview')
def cache_preview(body: CacheScope):
    try:
        return cache_manager.preview(body.scope)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post('/api/cache/clear')
def cache_clear(body: CacheToken):
    try:
        return cache_manager.execute(body.token)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get('/api/subject-model')
def subject_model(engine: Literal['auto','general','anime']='auto'):
    from .subject import backend
    encoder=backend(engine)
    return dict(installed=encoder.installed() if engine=='auto' else encoder.MODEL.exists(), version=encoder.VERSION,engine=engine)


class SubjectModelInstall(BaseModel):
    engine: Literal['auto','general','anime']='auto'


@app.post('/api/subject-model/install')
def install_subject_model(body: SubjectModelInstall):
    with service.lock:
        if service.status['running'] or service.sync_status['running']:
            raise HTTPException(409, '请等待扫描或同步结束后再安装模型')
        service.cancel.clear()
        service.update(running=True,phase='model_install',message='下载公共主体模型，不上传媒体',done=0,total=0,downloaded_bytes=0,started_at=time.time())
        def work():
            try:
                if body.engine=='auto':
                    from scripts.setup_subject_auto import install
                elif body.engine=='anime':
                    from scripts.setup_character import install
                else:
                    from scripts.setup_subject import install
                def progress(count):
                    if service.cancel.is_set():raise ValueError('模型下载已取消')
                    service.update(downloaded_bytes=count)
                install(progress=progress)
                service.update(phase='idle',message='主体模型已安装，可以开始分类')
            except Exception as exc:
                service.update(phase='error',message=str(exc))
            finally:
                service.update(running=False)
        service.scan_thread=threading.Thread(target=work,daemon=True)
        service.scan_thread.start()
        return dict(service.status)


@app.get('/api/groups')
def groups(page: int = 1, album: str = '', kind: str = 'all',
           sort: Literal['count', 'newest', 'oldest', 'size'] = 'count', q: str = ''):
    with service.lock:
        result = service.result
    selected = result['groups']
    if album:
        selected = [g for g in selected if any(p['album'] == album for p in g['photos'])]
    if kind == 'exact':
        selected = [g for g in selected if len({p['sha256'] for p in g['photos']}) == 1]
    elif kind == 'animated':
        selected = [g for g in selected if any(p.get('animated') for p in g['photos'])]
    elif kind == 'video':
        selected = [g for g in selected if any(p.get('media_type')=='video' for p in g['photos'])]
    if q:
        selected = [g for g in selected if any(q.casefold() in p['path'].casefold() for p in g['photos'])]
    date = lambda p: p.get('taken') or p.get('modified', 0)
    if sort == 'newest':
        selected = sorted(selected, key=lambda g: max(date(p) for p in g['photos']), reverse=True)
    elif sort == 'oldest':
        selected = sorted(selected, key=lambda g: min(date(p) for p in g['photos']))
    elif sort == 'size':
        selected = sorted(selected, key=lambda g: sum(p['size'] for p in g['photos']) if g.get('kind') in ('content','variants','subject') else g['potential_bytes'], reverse=True)
    else:
        selected = sorted(selected, key=lambda g: len(g['photos']), reverse=True)
    start = max(0, page - 1) * 20
    unmatched = filter_media(result.get('ungrouped', []), album, kind, q)
    return dict(groups=selected[start:start+20], total=len(selected), summary=result['summary'],
                ungrouped=dict(count=len(unmatched), covers=unmatched[:3], available='ungrouped' in result))


def filter_media(photos, album='', kind='all', q=''):
    return [p for p in photos if (not album or p['album']==album)
            and (not q or q.casefold() in p['path'].casefold())
            and (kind!='animated' or p.get('animated'))
            and (kind!='video' or p.get('media_type')=='video')
            and kind!='exact']


def result_media():
    return [p for g in service.result['groups'] for p in g['photos']] + service.result.get('ungrouped', [])


@app.get('/api/thumb/{key}')
def thumb(key: str):
    if not re.fullmatch('[a-f0-9]{64}', key):
        raise HTTPException(404)
    path = service.thumbs / (key + '.jpg')
    if not path.exists():
        return Response('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="200"><rect width="256" height="200" fill="#e3e9e0"/><g fill="none" stroke="#54634e" stroke-width="4"><rect x="88" y="65" width="80" height="65" rx="6"/><circle cx="110" cy="84" r="6"/><path d="m92 122 22-24 18 15 14-18 18 27M82 140l92-86"/></g></svg>',media_type='image/svg+xml',headers={'Cache-Control':'no-store'})
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control':'no-cache'})


@app.get('/api/original/{key}')
def original(key: str):
    """On-demand in-memory original. No disk cache or temporary image files."""
    with service.lock:
        p = next((dict(p) for p in service.catalog['photos'] if p['key'] == key), None)
        serial = service.catalog['serial']
        expected = next((p.get('sha256') for p in result_media() if p['key']==key), None)
    if not p or not serial:
        raise HTTPException(404, '图片已不在当前目录中，请同步手机目录')
    if p['size'] > 150*1024**2:
        raise HTTPException(413, '原图超过 150 MB 单图内存查看上限')
    if not original_slots.acquire(blocking=False):
        raise HTTPException(429, '原图读取正在进行，请稍后重试')
    try:
        raw = adb.read_photo(serial, p['path'])
        if len(raw) != p['size'] or expected and hashlib.sha256(raw).hexdigest() != expected:
            raise HTTPException(409, '手机文件已变化，请同步目录并重新分类')
        converted = False
        with Image.open(io.BytesIO(raw)) as source:
            mime = {'JPEG':'image/jpeg','PNG':'image/png','GIF':'image/gif','WEBP':'image/webp','BMP':'image/bmp'}.get(source.format)
            if not mime:
                converted = True
                output = io.BytesIO()
                ImageOps.exif_transpose(source).convert('RGBA').save(output,'PNG')
                raw = output.getvalue()
                mime = 'image/png'
        return Response(raw, media_type=mime, headers={'Cache-Control':'no-store, max-age=0',
                        'X-Content-Type-Options':'nosniff', 'X-Preview-Converted': '1' if converted else '0'})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, '无法读取手机原图：'+str(exc))
    finally:
        original_slots.release()


class OperationPlan(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=200)
    action: Literal['delete', 'move']
    target: str | None = None


class ExecutePlan(BaseModel):
    token: str


@app.post('/api/operations/preview')
def operation_preview(body: OperationPlan):
    try:
        return operations.prepare(body.keys, body.action, body.target)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post('/api/operations/execute')
def operation_execute(body: ExecutePlan):
    try:
        return operations.execute(body.token)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get('/api/groups/{group_id}')
def group_detail(group_id: int, page: int = 0, sort: str = 'reference', album: str = '', kind: str = 'all', q: str = ''):
    with service.lock:
        group = (dict(id=0,kind='ungrouped',potential_bytes=0,
                      photos=filter_media(service.result.get('ungrouped', []),album,kind,q)) if group_id==0 else
                 next((g for g in service.result['groups'] if g['id'] == group_id), None))
        if not group:
            raise HTTPException(404, '此相似组已不存在')
        photos = list(group['photos'])
        reference = photos[0]['key'] if photos and group_id else None
        date = lambda p: p.get('taken') or p.get('modified',0)
        if sort in ('newest','oldest'): photos.sort(key=date,reverse=sort=='newest')
        elif sort=='size': photos.sort(key=lambda p:p['size'],reverse=True)
        elif sort=='name': photos.sort(key=lambda p:p['path'].rsplit('/',1)[-1].casefold())
        total = len(photos)
        if page:
            page = min(max(1,page),max(1,(total+99)//100))
            photos = photos[(page-1)*100:page*100]
        return dict(group,photos=photos,total=total,page=page,reference_key=reference)


@app.get('/api/export.json')
def export_json():
    return JSONResponse(service.result, headers={'Content-Disposition': 'attachment; filename=photocluster.json'})


@app.get('/api/errors')
def errors():
    by_path={p['path']:p for p in service.catalog['photos']}
    return [dict(by_path.get(e['path'],{}),**{k:v for k,v in e.items() if k not in by_path.get(e['path'],{})}) for e in service.read_json('errors.json', [])]


@app.post('/api/video/{key}')
def prepare_video(key: str):
    with service.lock:
        photo=next((dict(p) for p in service.catalog['photos'] if p['key']==key),None)
        serial=service.catalog['serial']
        expected=next((p.get('sha256') for p in result_media() if p['key']==key),None)
    if not photo or photo.get('media_type')!='video':raise HTTPException(404)
    try:
        token=video_leases.create(serial,photo,expected)
        return {'token':token,'url':'/api/video-stream/'+token}
    except Exception as exc:raise HTTPException(503,str(exc))


@app.get('/api/video-stream/{token}')
def video_stream(token: str):
    path=video_leases.get(token)
    if not path:raise HTTPException(404,'视频预览已过期，请重新打开')
    return FileResponse(path,media_type='video/webm' if path.suffix=='.webm' else 'video/mp4',headers={'Cache-Control':'no-store'})


@app.post('/api/video-release/{token}')
def release_video(token: str):
    video_leases.release(token)
    return {'released':True}


@app.post('/api/video-keepalive/{token}')
def keep_video(token: str):
    return {'active':video_leases.get(token) is not None}


@app.get('/api/export.csv')
def export_csv():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['group', 'reference', 'path', 'album', 'bytes', 'width', 'height', 'sharpness', 'similarity', 'reason', 'taken_timestamp', 'modified_timestamp', 'animated'])
    for g in service.result['groups'] + [dict(id=0,photos=service.result.get('ungrouped', []))]:
        for index, p in enumerate(g['photos']):
            row = [g['id'], index == 0 and g['id']!=0, p['path'], p['album'], p['size'], p['width'], p['height'], p['sharpness'], p['score'], p['reason'], p.get('taken',0), p.get('modified',0), p.get('animated',False)]
            writer.writerow(["'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in row])
    return Response(buffer.getvalue().encode('utf-8-sig'), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=photocluster.csv'})


app.mount('/', StaticFiles(directory=ROOT / 'web', html=True), name='web')
