"""Optional SigLIP 2 evidence for bounded post-classification review, all local.

Semantic features are not identity probabilities. They can only supplement the
existing same-frame identity/region and perceptual checks, never replace them.
"""
import threading

import numpy as np
from PIL import Image

from .config import DATA
from . import perceptual, subject_merge

MODEL=DATA/'models/subject-complementary.onnx'
VERSION='siglip2-base-p16-224-int8-bilinear-pool-v1'
DIM=768
MAX_RETRIEVAL_FRAMES=16384  # 48 MiB float32 index; conservative coverage cap.
_session=None
_identity=None
_lock=threading.Lock()


def installed():
    return MODEL.is_file() and perceptual.installed()


def model_identity():
    from .semantic import file_identity
    return VERSION+':'+file_identity(MODEL)


def session():
    global _session,_identity
    identity=model_identity()
    with _lock:
        if _session is None or _identity!=identity:
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
            # Quantized graph is CPU-first; do not assume a CUDA-compatible export.
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _identity=identity
    return _session


def encode(images,cancelled=lambda:False):
    model=session();result=[]
    for offset in range(0,len(images),4):
        if cancelled():return None
        batch=np.stack([(np.asarray(im.convert('RGB').resize((224,224),Image.Resampling.BILINEAR),np.float32)/255-.5).transpose(2,0,1)/.5
                        for im in images[offset:offset+4]])
        value=np.asarray(model.run(['pooler_output'],{model.get_inputs()[0].name:batch})[0],np.float32)
        if value.shape!=(len(batch),DIM) or not np.isfinite(value).all():
            raise ValueError('Invalid complementary model output')
        result.extend(value/np.maximum(np.linalg.norm(value,axis=1,keepdims=True),1e-9))
    return np.asarray(result,np.float32)


class VectorCache(perceptual.VectorCache):
    def __init__(self,thumbs,cancelled=lambda:False,force=False):
        super().__init__(thumbs,cancelled,force,identity=model_identity(),encoder=encode,
                         database='subject-complementary.sqlite3',dim=DIM)


def verify(a,b,ga,gb,ca,cb,pa,pb,sa,sb,threshold,*,general_allowed=None):
    from .subject_auto import general_scores
    if any(len(x)!=len(a) for x in (ga,pa,sa)) or any(len(x)!=len(b) for x in (gb,pb,sb)):
        raise ValueError('Incompatible sampled frame caches')
    semantic=sa@sb.T;appearance=pa@pb.T
    cut=float(np.interp(threshold,[.65,.72,.80],[.90,.93,.96]))
    floor=float(np.interp(threshold,[.65,.72,.80],[.45,.50,.60]))
    region_cut=float(np.interp(threshold,[.65,.72,.80],[.52,.55,.65]))
    general=general_scores(a,b,region_cut)
    accepted=(~ga[:,None]&~gb[None,:]&(semantic>=cut)&(appearance>=floor)&(general>=region_cut))
    if general_allowed is not None:
        if general_allowed.shape!=accepted.shape:raise ValueError('Incompatible sampled frame caches')
        accepted &= general_allowed
    if ca is not None and cb is not None:
        if len(ca)!=len(a) or len(cb)!=len(b):raise ValueError('Incompatible sampled frame caches')
        identity=np.clip((1+ca@cb.T)/2,0,1)
        id_cut=float(np.interp(threshold,[.65,.72,.80],[.82,.82,.85]))
        sem_cut=float(np.interp(threshold,[.65,.72,.80],[.90,.92,.95]))
        # A stronger perceptual agreement is an alternative to stronger semantic
        # agreement. Both alternatives still need identity on this exact frame.
        appearance_cut=float(np.interp(threshold,[.65,.72,.80],[.60,.60,.70]))
        supported_semantic=float(np.interp(threshold,[.65,.72,.80],[.88,.88,.93]))
        evidence=((semantic>=sem_cut)&(appearance>=floor))|((semantic>=supported_semantic)&(appearance>=appearance_cut))
        accepted|=ga[:,None]&gb[None,:]&(identity>=id_cut)&evidence
    if not accepted.any():return None
    af,bf=np.unravel_index(int(np.where(accepted,semantic,-1).argmax()),accepted.shape)
    score=float(semantic[af,bf])
    return score,(score,int(af),int(bf)),'complementary'


def proposals(groups,photos,cache,scope,cancelled,progress):
    """Four distributed samples/group, four neighbor groups/sample, bounded math."""
    samples=[];owners=[];vectors=[]
    selections=[list(np.unique(np.linspace(0,len(g)-1,min(4,len(g))).astype(int))) if len(g)>=2 else [] for g in groups]
    # Give each established group a sample before spending room on extra views.
    for slot in range(4):
        for j,positions in enumerate(selections):
            if len(positions)>slot:
                samples.append(groups[j][positions[slot]]);owners.append(j)
    frames=0
    for done,i in enumerate(samples):
        if cancelled():raise subject_merge.Cancelled()
        value=cache.get(photos[i])
        if value is None:raise subject_merge.Cancelled()
        if frames+len(value)>MAX_RETRIEVAL_FRAMES:break
        frames+=len(value)
        vectors.append(value)
        if progress:progress(done+1,len(samples),'subject_complement')
    samples=samples[:len(vectors)];owners=owners[:len(vectors)]
    if not samples:return []
    flat=np.concatenate(vectors);frame_owners=np.repeat(owners,[len(v) for v in vectors])
    result=[]
    for done,(i,owner,v) in enumerate(zip(samples,owners,vectors)):
        if cancelled():raise subject_merge.Cancelled()
        best={}
        for offset in range(0,len(flat),2048):
            if cancelled():raise subject_merge.Cancelled()
            scores=(v@flat[offset:offset+2048].T).max(axis=0)
            for at in np.flatnonzero(scores>=.88):
                other=int(frame_owners[offset+at])
                if other==owner:continue
                if scope=='album' and photos[i]['album']!=photos[groups[other][0]]['album']:continue
                best[other]=max(best.get(other,0),float(scores[at]))
        result.extend((owner,other,i,score) for other,score in sorted(best.items(),key=lambda x:(-x[1],x[0]))[:4])
        if progress:progress(done+1,len(samples),'subject_complement_match')
    return result
