"""Local CCIP identity features for single-character anime imagery.

CCIP is trained for character similarity; DINOv2's general scene/region score is
not an identity veto here. No colour-equality or pose-alignment requirement.
Upstream preprocessing and the (1 - cosine) / 2 distance are preserved.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import threading

import numpy as np
from PIL import Image

from .config import DATA

MODEL=DATA/'models/ccip-caformer-24.onnx'
VERSION='ccip-caformer24-bilinear384-v1'
DIM=768
DEFAULT_DISTANCE=.17847511429108218
DEFAULT_THRESHOLD=1-DEFAULT_DISTANCE
_session=None
_identity=None
_lock=threading.Lock()


def model_identity():
    from .semantic import file_identity
    return VERSION+':'+file_identity(MODEL)


def session():
    global _session,_identity
    identity=model_identity()
    with _lock:
        if _session is None or identity!=_identity:
            if not MODEL.exists():raise ValueError('请先安装本地动漫角色模型')
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _identity=identity
    return _session


def preprocess(image):
    # The upstream CCIP encoder expects a stretched RGB square, not CLIP cropping
    # or DINO letterboxing. Do not add grayscale recolouring to the trained input.
    image=image.convert('RGB').resize((384,384),Image.Resampling.BILINEAR)
    array=np.asarray(image,np.float32)/255
    return ((array-np.array([.48145466,.4578275,.40821073],np.float32))/np.array([.26862954,.26130258,.27577711],np.float32)).transpose(2,0,1)


def encode(images):
    model=session();result=[]
    for offset in range(0,len(images),4):
        batch=np.stack([preprocess(im) for im in images[offset:offset+4]])
        vectors=model.run(None,{model.get_inputs()[0].name:batch})[0]
        if vectors.ndim!=2 or vectors.shape[1]!=DIM or not np.isfinite(vectors).all():
            raise ValueError('Invalid character model output')
        result.extend(vectors/np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-9))
    return np.asarray(result,np.float32)


def vectors(photos,thumbs,progress,cancelled,force):
    from .subject import frames
    result=[];identity=model_identity()
    with closing(sqlite3.connect(Path(thumbs)/'characters.sqlite3',timeout=30)) as con,con:
        con.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, sha TEXT, version TEXT, data BLOB)')
        for i,p in enumerate(photos):
            if cancelled():return None
            row=None if force else con.execute('SELECT sha,version,data FROM vectors WHERE key=?',(p['key'],)).fetchone()
            if row and row[:2]==(p['sha256'],identity):
                v=np.frombuffer(row[2],np.float32).reshape(-1,DIM)
            else:
                v=encode(frames(p,thumbs))
                con.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)',(p['key'],p['sha256'],identity,v.tobytes()))
            result.append(v)
            if i%32==0:con.commit()
            if progress:progress(i+1,len(photos),'character_embedding')
    return result


def similarity(a,b):
    scores=np.clip((1+a@b.T)/2,0,1)
    af,bf=np.unravel_index(int(scores.argmax()),scores.shape)
    return float(scores[af,bf]),int(af),int(bf)


def cluster(photos,thumbs,scope='all',threshold=DEFAULT_THRESHOLD,progress=None,cancelled=lambda:False,force=False):
    from .vision import quality
    from .acceleration import cpu_budget
    ordered=sorted(photos,key=quality,reverse=True)
    with cpu_budget():
        values=vectors(ordered,thumbs,progress,cancelled,force)
        if values is None:return None
        # Only reference frames are indexed; matched items cannot create chains.
        matrix=np.empty((sum(len(v) for v in values),DIM),np.float32)
        owners=np.empty(len(matrix),np.int32);used=0;groups=[];reps=[];exact={}
        for i,(p,v) in enumerate(zip(ordered,values)):
            if cancelled():return None
            identity=(p['sha256'],p['album'] if scope=='album' else '')
            if identity in exact:
                j=exact[identity]
                groups[j].append(dict(p,score=1.,reason='文件完全相同',relation='exact'))
            else:
                candidates=set();best=None
                for offset in range(0,used,4096):
                    scores=np.max((1+v@matrix[offset:min(used,offset+4096)].T)/2,axis=0)
                    candidates.update(owners[offset:offset+len(scores)][scores>=threshold-1e-6].tolist())
                for j in sorted(candidates):
                    if scope=='album' and p['album']!=ordered[reps[j]]['album']:continue
                    score,af,bf=similarity(values[reps[j]],v)
                    if score>=threshold and (best is None or score>best[1]):best=(j,score,af,bf)
                if best:
                    j,score,af,bf=best
                    groups[j].append(dict(p,score=round(min(score,.999),4),relation='character',reason='动漫角色身份特征相近（CCIP），请人工确认',match_frame=bf,reference_frame=af))
                else:
                    j=len(groups);groups.append([dict(p,score=1.,reason='动漫角色组参考',relation='reference')]);reps.append(i)
                    matrix[used:used+len(v)]=v;owners[used:used+len(v)]=j;used+=len(v)
                    exact[identity]=j  # Only exact copies of the reference get score 1.
            if progress:progress(i+1,len(ordered),'character_match')
        return sorted([g for g in groups if len(g)>1],key=len,reverse=True)
