"""Local CLIP frame embeddings and cross-format visual-content grouping."""
import json
import threading
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .config import MODEL
VERSION='clip-vit-b32-int8-v1'
_session=None
_lock=threading.Lock()


def session():
    global _session
    with _lock:
        if _session is None:
            if not MODEL.exists():raise RuntimeError('内容模型未安装，请运行 scripts/setup_semantic.py')
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
        return _session


def preprocess(image):
    # Official CLIP RGB normalization, shortest-side resize and center crop.
    image=image.convert('RGB');w,h=image.size;scale=224/min(w,h)
    image=image.resize((round(w*scale),round(h*scale)),Image.Resampling.BICUBIC)
    image=ImageOps.fit(image,(224,224),method=Image.Resampling.BICUBIC)
    array=np.asarray(image,np.float32)/255
    array=(array-np.array([.48145466,.4578275,.40821073],np.float32))/np.array([.26862954,.26130258,.27577711],np.float32)
    return array.transpose(2,0,1)


def embeddings(images):
    result=[];model=session()
    for offset in range(0,len(images),8):
        batch=np.stack([preprocess(image) for image in images[offset:offset+8]])
        outputs=model.run(None,{model.get_inputs()[0].name:batch})
        vector=next(x for x in outputs if x.ndim==2 and x.shape[-1]==512)
        vector=vector/np.maximum(np.linalg.norm(vector,axis=1,keepdims=True),1e-9)
        result.extend(vector)
    return np.array(result,np.float32)


def ensure_embeddings(photo,thumbs,force=False):
    target=Path(thumbs)/(photo['key']+'.clip.npz')
    if not force and target.exists():
        with np.load(target) as cache:
            if str(cache['version'])==VERSION and str(cache['sha256'])==photo['sha256']:
                return cache['vectors']
    if photo.get('frame_path') and Path(photo['frame_path']).exists():
        with np.load(photo['frame_path']) as archive:frames=archive['frames']
        images=[Image.fromarray(frame) for frame in frames]
    elif photo.get('animation_samples'):
        import base64
        images=[Image.fromarray(np.frombuffer(base64.b64decode(s),np.uint8).reshape(64,64,3)) for s in photo['animation_samples'][::2]]
        with Image.open(Path(thumbs)/(photo['key']+'.jpg')) as cover:images.insert(0,cover.convert('RGB'))
    else:
        with Image.open(Path(thumbs)/(photo['key']+'.jpg')) as image:images=[image.convert('RGB')]
    vectors=embeddings(images)
    np.savez_compressed(target,vectors=vectors,version=VERSION,sha256=photo['sha256'])
    return vectors


def similarity(a,b):
    matrix=a@b.T
    best=np.unravel_index(int(matrix.argmax()),matrix.shape)
    # At least one shared scene can relate different excerpts; broad grouping
    # is explicitly a content relation, never a duplicate/deletion verdict.
    return float(matrix[best]),int(best[0]),int(best[1])


def load_vectors(ordered,thumbs,progress,cancelled,force):
    """One bulk DB read replaces thousands of zip/file opens on warm scans."""
    database=Path(thumbs)/'embeddings.sqlite3'
    with sqlite3.connect(database,timeout=30) as con:
        con.execute('CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, sha TEXT, version TEXT, vector BLOB)')
        cached={} if force else {key:(sha,version,blob) for key,sha,version,blob in con.execute('SELECT * FROM embeddings')}
        vectors=[None]*len(ordered);missing=[]
        for i,p in enumerate(ordered):
            row=cached.get(p['key'])
            if row and row[0]==p['sha256'] and row[1]==VERSION:
                vectors[i]=np.frombuffer(row[2],np.float32).reshape(-1,512)
            else:missing.append((i,p))
        done=len(ordered)-len(missing)
        if progress:progress(done,len(ordered),'embedding')
        # Bound queue and parallelize legacy-cache reads, not concurrent model runs.
        def read(item):
            i,p=item
            return i,ensure_embeddings(p,thumbs,force)
        for offset in range(0,len(missing),64):
            if cancelled():return None
            chunk=missing[offset:offset+64]
            # Serialize inference; legacy cache files can be decompressed in parallel.
            existing=[x for x in chunk if not force and (Path(thumbs)/(x[1]['key']+'.clip.npz')).exists()]
            existing_indices={i for i,p in existing}
            absent=[x for x in chunk if x[0] not in existing_indices]
            with ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(read,existing))
            results.extend(read(x) for x in absent)
            for i,v in results:
                vectors[i]=v;p=ordered[i]
                con.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)',(p['key'],p['sha256'],VERSION,v.astype(np.float32).tobytes()))
            con.commit();done+=len(chunk)
            if progress:progress(done,len(ordered),'embedding')
    return vectors


def cluster(photos,thumbs,scope='all',threshold=.84,progress=None,cancelled=lambda:False,force=False):
    from .vision import quality
    ordered=sorted(photos,key=quality,reverse=True)
    vectors=load_vectors(ordered,thumbs,progress,cancelled,force)
    if vectors is None:return None
    if not ordered:return []
    # Native matrix retrieval over frame embeddings, not Python all-pair loops.
    capacity=sum(len(v) for v in vectors)
    representatives=np.empty((capacity,512),np.float32);owners=np.empty(capacity,np.int32)
    used=0;groups=[];reps=[];exact={}
    from .acceleration import FrameSearch, cuda, fallback
    search=None;active={}
    if len(ordered)>=128 and cuda() is not None:
        try:search=FrameSearch(vectors)
        except Exception as exc:
            search=None;fallback('GPU 检索初始化失败，使用 CPU：'+str(exc))
    for i,(p,v) in enumerate(zip(ordered,vectors)):
        if cancelled():return None
        identity=(p['sha256'],p['album'] if scope=='album' else '')
        if identity in exact:
            groups[exact[identity]].append(dict(p,score=1.,reason='文件完全相同',relation='exact'))
            if progress:progress(i+1,len(ordered),'content_match')
            continue
        candidates=[]
        if used and search is not None:
            try:candidates=search.candidates(i,active,threshold)
            except Exception as exc:
                search=None;fallback('GPU 检索失败，使用 CPU：'+str(exc))
        if used and search is None:
            scores=np.max(v@representatives[:used].T,axis=0)
            positions=np.flatnonzero(scores>=threshold)
            candidates=np.unique(owners[positions]).tolist()
        best=None
        for j in candidates:
            if scope=='album' and reps[j]['album']!=p['album']:continue
            score,af,bf=similarity(vectors[reps[j]['_index']],v)
            if score<threshold:continue
            if best is None or score>best[1]:best=(j,score,af,bf)
        if best:
            j,score,af,bf=best
            groups[j].append(dict(p,score=round(min(score,.999),4),relation='content',
                reason='视觉内容相近（CLIP 关键帧），不是重复判定',match_frame=bf,reference_frame=af))
        else:
            j=len(groups);groups.append([dict(p,score=1.,reason='内容组参考',relation='reference')]);reps.append(dict(p,_index=i))
            representatives[used:used+len(v)]=v;owners[used:used+len(v)]=j;used+=len(v);exact[identity]=j
            active[i]=j
        if progress:progress(i+1,len(ordered),'content_match')
    return sorted([g for g in groups if len(g)>1],key=len,reverse=True)
