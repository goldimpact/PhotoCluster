"""Experimental automatic subject grouping with local DINOv2 region features.

This is visual subject retrieval, not a trained character identity classifier.
Every match is checked against the group's original representative, never chains.
"""
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .config import DATA

MODEL = DATA / 'models/dinov2-small-int8.onnx'
VERSION = 'dinov2-small-int8-regions-v1'
DIM = 384
_session = None
_identity = None
_lock = threading.Lock()


def backend(engine='general'):
    if engine=='anime':
        from . import character
        return character
    if engine!='general':raise ValueError('Unknown subject engine')
    import sys
    return sys.modules[__name__]


def model_identity():
    from .semantic import file_identity
    return VERSION + ':' + file_identity(MODEL)


def session():
    global _session, _identity
    identity = model_identity()
    with _lock:
        if _session is None or identity != _identity:
            if not MODEL.exists():
                raise ValueError('请先安装本地主体模型')
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options = ort.SessionOptions(); options.intra_op_num_threads = 4; options.inter_op_num_threads = 1
            _session = ort.InferenceSession(str(MODEL), sess_options=options, providers=['CPUExecutionProvider'])
            _identity = identity
    return _session


def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def preprocess(image):
    # Preserve off-centre subjects. A whole-frame letterbox avoids CLIP's centre crop.
    image = ImageOps.pad(image.convert('RGB'), (224,224), method=Image.Resampling.BICUBIC, color=(124,116,104))
    array = np.asarray(image, np.float32)/255
    return ((array-np.array([.485,.456,.406], np.float32))/np.array([.229,.224,.225], np.float32)).transpose(2,0,1)


def encode(images):
    model = session(); result = []
    for start in range(0, len(images), 4):
        batch = np.stack([preprocess(x) for x in images[start:start+4]])
        outputs = model.run(None, {model.get_inputs()[0].name: batch})
        tokens = next(x for x in outputs if x.ndim == 3 and x.shape[-1] == DIM)
        for frame in tokens:
            patches = frame[1:].reshape(16,16,DIM)
            # One inference produces global and overlapping regional descriptors.
            # Regions help local subjects survive background/composition changes.
            regions = [frame[0], patches.mean(axis=(0,1))]
            for y,x in ((0,0),(0,6),(6,0),(6,6)):
                regions.append(patches[y:y+10,x:x+10].mean(axis=(0,1)))
            result.append(unit(np.stack(regions)))
    return np.asarray(result, np.float32)


def frames(photo, thumbs):
    from .semantic import frame_images
    images = frame_images(photo, thumbs)
    # Bounded at eight frames, evenly distributed across the already extracted timeline.
    if len(images) > 8:
        images = [images[i] for i in np.linspace(0,len(images)-1,8,dtype=int)]
    return images


def vectors(photos, thumbs, progress, cancelled, force):
    identity = model_identity(); result = []
    with closing(sqlite3.connect(Path(thumbs)/'subjects.sqlite3', timeout=30)) as con, con:
        con.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, sha TEXT, version TEXT, data BLOB)')
        for i,p in enumerate(photos):
            if cancelled():
                return None
            row = None if force else con.execute('SELECT sha,version,data FROM vectors WHERE key=?', (p['key'],)).fetchone()
            if row and row[:2] == (p['sha256'], identity):
                v = np.frombuffer(row[2], np.float32).reshape(-1,6,DIM)
            else:
                v = encode(frames(p, thumbs))
                con.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)', (p['key'],p['sha256'],identity,v.tobytes()))
            result.append(v)
            if i % 32 == 0:
                con.commit()
            if progress:
                progress(i+1,len(photos),'subject_embedding')
    return result


def similarity(a, b):
    global_score = a[:,0] @ b[:,0].T
    local_score = np.max(np.einsum('frd,gsd->fgrs',a[:,1:],b[:,1:]),axis=(2,3))
    score = .4*global_score + .6*local_score
    # A shared background region alone must not join unrelated whole images.
    score = np.where(global_score >= .45, score, -1)
    af,bf = np.unravel_index(int(score.argmax()),score.shape)
    return float(score[af,bf]), int(af), int(bf)


def cluster(photos, thumbs, scope='all', threshold=.72, progress=None, cancelled=lambda:False, force=False):
    from .vision import quality
    from .acceleration import cpu_budget
    ordered = sorted(photos,key=quality,reverse=True)
    with cpu_budget():
        values = vectors(ordered,thumbs,progress,cancelled,force)
        if values is None:
            return None
        groups=[]; reps=[]; exact={}
        # Bounded float32 matrix retrieval uses the same score as verification,
        # retaining every possible direct match without Python all-pair scoring.
        capacity = sum(len(v) for v in values)
        matrix=np.empty((capacity,6,DIM),np.float32); owners=np.empty(capacity,np.int32); used=0
        for i,(photo,v) in enumerate(zip(ordered,values)):
            if cancelled():
                return None
            key=(photo['sha256'], photo['album'] if scope=='album' else '')
            if key in exact:
                j=exact[key]; groups[j].append(dict(photo,score=1.,reason='文件完全相同',relation='exact'))
            else:
                best=None
                candidates=set()
                for offset in range(0,used,512):
                    block=matrix[offset:min(used,offset+512)]
                    whole=v[:,0] @ block[:,0].T
                    local=(v[:,1:].reshape(-1,DIM) @ block[:,1:].reshape(-1,DIM).T).reshape(len(v),5,len(block),5).max(axis=(1,3))
                    scores=np.max(np.where(whole>=.45,.4*whole+.6*local,-1),axis=0)
                    candidates.update(owners[offset:offset+len(block)][scores>=threshold-1e-6].tolist())
                for j in sorted(candidates):
                    if scope=='album' and photo['album']!=ordered[reps[j]]['album']:
                        continue
                    score,af,bf=similarity(values[reps[j]],v)
                    if score>=threshold and (best is None or score>best[1]):
                        best=(j,score,af,bf)
                if best:
                    j,score,af,bf=best
                    groups[j].append(dict(photo,score=round(min(score,.999),4),reason='主体外观与局部区域相近（DINOv2），请确认身份',relation='subject',reference_frame=af,match_frame=bf))
                else:
                    j=len(groups);groups.append([dict(photo,score=1.,reason='主体组参考',relation='reference')]);reps.append(i)
                    matrix[used:used+len(v)]=v;owners[used:used+len(v)]=j;used+=len(v)
                exact[key]=j
            if progress:
                progress(i+1,len(ordered),'subject_match')
        return sorted([g for g in groups if len(g)>1],key=len,reverse=True)
