"""One subject workflow with bounded, frame-specific supplemental evidence.

All media enter the general route. A style classifier can enable additional
character evidence; it never partitions the library or decides subject identity.
This is not universal identity recognition. Routing can be wrong, too.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import threading

import numpy as np
from PIL import Image

from . import subject, character
from .config import DATA

MODEL=DATA/'models/subject-routing.onnx'
VERSION='subject-auto-frame-routing-v1'
ROUTING_VERSION='mobilenetv3-v15-bilinear-half384-v1'
_session=None
_identity=None
_lock=threading.Lock()


def installed():
    return all(p.exists() for p in (MODEL,subject.MODEL,character.MODEL))


def routing_identity():
    from .semantic import file_identity
    return ROUTING_VERSION+':'+subject.VERSION+':'+file_identity(MODEL)


def model_identity():
    return ':'.join((VERSION,subject.model_identity(),character.model_identity(),routing_identity()))


def session():
    global _session,_identity
    identity=routing_identity()
    with _lock:
        if _session is None or _identity!=identity:
            if not MODEL.exists():raise ValueError('请先准备主体识别资源')
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _identity=identity
    return _session


def routing_scores(images):
    model=session();result=[]
    for image in images:
        # Upstream generic classifier: RGB/BILINEAR 384, mean/std .5.
        a=np.asarray(image.convert('RGB').resize((384,384),Image.Resampling.BILINEAR),np.float32)/255
        batch=((a-.5)/.5).transpose(2,0,1)[None]
        outputs=dict(zip([x.name for x in model.get_outputs()],model.run(None,{model.get_inputs()[0].name:batch})))
        values=outputs.get('output')
        if values is None:values=next(iter(outputs.values()))
        values=np.asarray(values).reshape(-1)
        if len(values)!=5 or not np.isfinite(values).all():raise ValueError('Invalid routing model output')
        result.append(values)
    return np.asarray(result,np.float32)


def eligible(scores):
    # Upstream labels: 3d, bangumi, comic, illustration, not_painting.
    # Conservative supplemental gate, not a single-character detector. All
    # rejected/uncertain frames still participate in general visual matching.
    return scores[:,[0,1,3]].sum(axis=1)>=.8


def load_routes(photos,thumbs,progress,cancelled,force):
    result=[];identity=routing_identity()
    with closing(sqlite3.connect(Path(thumbs)/'subject-routing.sqlite3',timeout=30)) as con,con:
        con.execute('CREATE TABLE IF NOT EXISTS routes (key TEXT PRIMARY KEY, sha TEXT, version TEXT, data BLOB)')
        for i,p in enumerate(photos):
            if cancelled():return None
            row=None if force else con.execute('SELECT sha,version,data FROM routes WHERE key=?',(p['key'],)).fetchone()
            if row and row[:2]==(p['sha256'],identity):scores=np.frombuffer(row[2],np.float32).reshape(-1,5)
            else:
                scores=routing_scores(subject.frames(p,thumbs))
                con.execute('INSERT OR REPLACE INTO routes VALUES (?,?,?,?)',(p['key'],p['sha256'],identity,scores.tobytes()))
            result.append(eligible(scores))
            if i%32==0:con.commit()
            if progress:progress(i+1,len(photos),'subject_routing')
    return result


def character_threshold(threshold):
    # One user strictness control; model scores have distinct scales.
    return float(np.interp(threshold,[.65,.72,.80],[.78,character.DEFAULT_THRESHOLD,.85]))


def choose_match(general,extra,threshold):
    choices=[]
    for value,cut in ((general,threshold),(extra,character_threshold(threshold))):
        if value is not None and value[0]>=cut:
            choices.append(((value[0]-cut)/max(1-cut,1e-6),value))
    return max(choices,key=lambda x:x[0])[1] if choices else None


def cluster(photos,thumbs,scope='all',threshold=.72,progress=None,cancelled=lambda:False,force=False):
    from .vision import quality
    from .acceleration import cpu_budget
    ordered=sorted(photos,key=quality,reverse=True)
    with cpu_budget():
        general=subject.vectors(ordered,thumbs,progress,cancelled,force)
        if general is None:return None
        gates=load_routes(ordered,thumbs,progress,cancelled,force)
        if gates is None:return None
        selected=[i for i,mask in enumerate(gates) if mask.any()]
        def report(done,total,phase):
            if progress:progress(done,total,'subject_supplement')
        extra=character.vectors([ordered[i] for i in selected],thumbs,report,cancelled,force) if selected else []
        if extra is None:return None
        characters=dict(zip(selected,extra))
        for i in selected:
            if len(characters[i])!=len(gates[i]):raise ValueError('Incompatible sampled frame caches')
        gm=np.empty((sum(len(v) for v in general),6,subject.DIM),np.float32)
        go=np.empty(len(gm),np.int32);gu=0
        cm=np.empty((sum(int(gates[i].sum()) for i in selected),character.DIM),np.float32)
        co=np.empty(len(cm),np.int32);cu=0
        reps=[];groups=[];exact={};ct=character_threshold(threshold)
        for i,(p,v) in enumerate(zip(ordered,general)):
            if cancelled():return None
            identity=(p['sha256'],p['album'] if scope=='album' else '')
            if identity in exact:
                groups[exact[identity]].append(dict(p,score=1.,reason='文件完全相同',relation='exact'))
            else:
                candidates=set();best=None
                for offset in range(0,gu,512):
                    block=gm[offset:min(gu,offset+512)]
                    whole=v[:,0]@block[:,0].T
                    local=(v[:,1:].reshape(-1,subject.DIM)@block[:,1:].reshape(-1,subject.DIM).T).reshape(len(v),5,len(block),5).max(axis=(1,3))
                    scores=np.max(np.where(whole>=.45,.4*whole+.6*local,-1),axis=0)
                    candidates.update(go[offset:offset+len(block)][scores>=threshold-1e-6].tolist())
                cv=characters[i][gates[i]] if i in characters else None
                if cv is not None:
                    for offset in range(0,cu,4096):
                        scores=np.max((1+cv@cm[offset:min(cu,offset+4096)].T)/2,axis=0)
                        candidates.update(co[offset:offset+len(scores)][scores>=ct-1e-6].tolist())
                for j in sorted(candidates):
                    r=reps[j]
                    if scope=='album' and p['album']!=ordered[r]['album']:continue
                    g=subject.similarity(general[r],v);e=None
                    if cv is not None and r in characters:
                        score,af,bf=character.similarity(characters[r][gates[r]],cv)
                        e=(score,int(np.flatnonzero(gates[r])[af]),int(np.flatnonzero(gates[i])[bf]))
                        # When both frames are in the supplemental route, the
                        # identity evidence resolves disagreement. Do not let
                        # similar style/background overrule a negative match.
                        if gates[r][g[1]] and gates[i][g[2]]:g=None
                    chosen=choose_match(g,e,threshold)
                    if chosen:
                        cut=threshold if chosen is g else ct
                        margin=(chosen[0]-cut)/max(1-cut,1e-6)
                        if best is None or margin>best[0]:best=(margin,j,chosen)
                if best:
                    _,j,(score,af,bf)=best
                    groups[j].append(dict(p,score=round(min(score,.999),4),relation='subject',reason='主体特征相近，请人工确认',reference_frame=af,match_frame=bf))
                else:
                    j=len(groups);groups.append([dict(p,score=1.,reason='主体组参考',relation='reference')]);reps.append(i)
                    gm[gu:gu+len(v)]=v;go[gu:gu+len(v)]=j;gu+=len(v)
                    if cv is not None:cm[cu:cu+len(cv)]=cv;co[cu:cu+len(cv)]=j;cu+=len(cv)
                    exact[identity]=j
            if progress:progress(i+1,len(ordered),'subject_match')
        return sorted([g for g in groups if len(g)>1],key=len,reverse=True)
