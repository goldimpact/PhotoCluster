"""Explicit user actions on real phone files; virtual groups never become directories."""
import hashlib
import json
import os
import posixpath
import secrets
import shutil
import shlex
import time
from urllib.parse import quote

from . import adb


def shell(serial, command):
    return adb.run(['-s', serial, 'shell', command]).decode('utf-8', 'replace').strip()


def exists(serial, path):
    return shell(serial, 'if test -e ' + shlex.quote(path) + '; then echo yes; else echo no; fi') == 'yes'


def sync_media(serial, path):
    try:
        response = shell(serial, 'content call --uri content://media --method scan_file --arg ' + shlex.quote(path))
        if 'Exception' in response or 'Error' in response:
            raise RuntimeError(response)
        return None
    except Exception:
        try:
            shell(serial, 'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d ' + shlex.quote('file://' + quote(path)))
            return '已发送媒体扫描通知；部分手机相册可能稍后才更新'
        except Exception as exc:
            return '文件操作成功，但媒体库刷新失败：' + str(exc)


class Operations:
    def __init__(self, service):
        self.service = service
        self.plans = {}

    def prepare(self, keys, action, target=None):
        s = self.service
        with s.lock:
            if s.status['running'] or s.sync_status['running']:
                raise ValueError('扫描期间不能操作手机文件')
            if action not in ('delete', 'move'):
                raise ValueError('仅支持删除或移动到真实相册，不支持向虚拟组新增')
            if not keys or len(keys) > 200 or len(set(keys)) != len(keys):
                raise ValueError('每次请选择 1–200 个不同的媒体文件')
            serial = s.catalog['serial']
            if not s.result.get('summary') or serial != s.result['summary']['serial']:
                raise ValueError('当前设备与分类结果不一致，请重新扫描')
            catalog = {p['key']: p for p in s.catalog['photos']}
            grouped = {p['key']: p for g in s.result['groups'] for p in g['photos']}
            grouped.update({p['key']: p for p in s.result.get('ungrouped', [])})
            albums = {p['album'] for p in catalog.values()}
            if action == 'move' and target not in albums:
                raise ValueError('目标必须是手机中已发现的真实相册目录')
            items = []
            for key in keys:
                if key not in catalog or key not in grouped:
                    raise ValueError('媒体已经变化，请刷新结果')
                p = grouped[key]
                path = p['path']
                if any(c in path for c in ('\n', '\r', '\x00')) or not path.startswith('/storage/') or posixpath.normpath(path) != path:
                    raise ValueError('不支持操作这个存储路径')
                destination = posixpath.join(target, posixpath.basename(path)) if action == 'move' else None
                if destination == path:
                    raise ValueError('媒体已在目标相册内：' + path)
                if destination and any(x['destination'] == destination for x in items):
                    raise ValueError('选中的媒体包含同名文件，不能移动到同一目录')
                items.append(dict(key=key, source=path, destination=destination, sha256=p['sha256']))
            token = secrets.token_urlsafe(32)
            plan = dict(token=token, serial=serial, action=action, items=items, created_at=time.time())
            self.plans = {k: v for k, v in self.plans.items() if time.time()-v['created_at'] < 600}
            self.plans[token] = plan
            return plan

    def journal(self, event):
        with (self.service.data / 'operations.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(time=time.time(), **event), ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def execute(self, token):
        s = self.service
        with s.lock:
            if s.status['running'] or s.sync_status['running']:
                raise ValueError('扫描期间不能操作手机文件')
            plan = self.plans.pop(token, None)
            if not plan or time.time()-plan['created_at'] > 600:
                raise ValueError('操作预览已失效，请重新选择')
            if s.catalog['serial'] != plan['serial']:
                raise ValueError('手机设备已切换')
            serial = plan['serial']
            results = []
            for item in plan['items']:
                source, destination = item['source'], item['destination']
                result = dict(source=source, destination=destination, ok=False)
                try:
                    current = next((p for p in s.catalog['photos'] if p['key'] == item['key']), None)
                    if not current or current['path'] != source:
                        raise ValueError('媒体路径已经改变')
                    qsource = shlex.quote(source)
                    if shell(serial, f'if test -f {qsource} && test ! -L {qsource}; then echo yes; fi') != 'yes':
                        raise ValueError('源文件不存在或不是普通媒体文件')
                    if hashlib.sha256(adb.read_photo(serial, source)).hexdigest() != item['sha256']:
                        raise ValueError('手机原图内容已变化，取消此文件操作，请重新扫描')
                    if destination:
                        qdest = shlex.quote(destination)
                        if exists(serial, destination):
                            raise ValueError('目标已存在同名文件，不会覆盖')
                        if shell(serial, 'if test -d ' + shlex.quote(posixpath.dirname(destination)) + '; then echo yes; fi') != 'yes':
                            raise ValueError('目标相册目录已不存在')
                    self.journal(dict(event='intent', serial=serial, action=plan['action'], **item))
                    if destination:
                        shell(serial, f'mv -n -- {qsource} {qdest}')
                        if exists(serial, source) or not exists(serial, destination):
                            raise RuntimeError('移动未完成，原文件保留；请刷新手机相册')
                    else:
                        shell(serial, f'rm -- {qsource}')
                        if exists(serial, source):
                            raise RuntimeError('文件仍存在，删除未完成')
                    result['ok'] = True
                    self.reconcile(item, destination)
                    warnings = [sync_media(serial, path) for path in (source, destination) if path]
                    result['warnings'] = [w for w in warnings if w]
                    self.journal(dict(event='done', serial=serial, action=plan['action'], **item))
                except Exception as exc:
                    result['error'] = str(exc)
                    # Record each failure separately; a batch is not atomic.
                    self.journal(dict(event='error', serial=serial, **item, error=str(exc), changed=result['ok']))
                results.append(result)
            s.save('catalog.json', s.catalog)
            s.save('groups.json', s.result)
            return dict(results=results, succeeded=sum(r['ok'] for r in results))

    def reconcile(self, item, destination):
        s = self.service
        key = item['key']
        if destination:
            album = posixpath.dirname(destination)
            old = next(p for p in s.catalog['photos'] if p['key'] == key)
            new_key = s.key(s.catalog['serial'], dict(old, path=destination))
            for suffix in ('.jpg', '.npz', '.frames.npz', '.clip.npz', '.variants.npz'):
                cached_file = s.thumbs / (key + suffix)
                if cached_file.exists():
                    shutil.copyfile(cached_file, s.thumbs / (new_key + suffix))
            with s.connect() as con:
                cached = con.execute('SELECT payload FROM features WHERE key=?', (key,)).fetchone()
                if cached:
                    payload = json.loads(cached[0])
                    payload['feature_path'] = str(s.thumbs / (new_key + '.npz'))
                    if payload.get('frame_path'):
                        payload['frame_path'] = str(s.thumbs / (new_key + '.frames.npz'))
                    con.execute('INSERT OR REPLACE INTO features VALUES (?,?)', (new_key, json.dumps(payload)))
            for p in s.catalog['photos'] + [p for g in s.result['groups'] for p in g['photos']] + s.result.get('ungrouped', []):
                if p['key'] == key:
                    p.update(path=destination, album=album, album_name=posixpath.basename(album), key=new_key)
        else:
            s.catalog['photos'] = [p for p in s.catalog['photos'] if p['key'] != key]
            s.result['ungrouped'] = [p for p in s.result.get('ungrouped', []) if p['key'] != key]
            for g in s.result['groups']:
                g['photos'] = [p for p in g['photos'] if p['key'] != key]
        s.normalize_groups()
        for g in s.result['groups']:
            g['potential_bytes'] = 0 if g.get('kind') in ('content','variants','subject') else sum(p['size'] for p in g['photos'][1:])
        s.result['summary'].update(groups=len(s.result['groups']),
                                   ungrouped=len(s.result.get('ungrouped', [])),
                                   grouped_photos=sum(len(g['photos']) for g in s.result['groups']),
                                   potential_bytes=sum(g['potential_bytes'] for g in s.result['groups']))
