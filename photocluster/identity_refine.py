"""Optional larger CCIP for rejected character candidates, never general identity."""
import threading

import numpy as np

from . import character, perceptual
from .config import DATA

MODEL=DATA/'models/subject-identity-refine.onnx'
VERSION='ccip-caformer-b36-24-bilinear384-v1'
DIM=768
_session=None
_identity=None
_lock=threading.Lock()


def installed():
    return MODEL.is_file()


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
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _identity=identity
    return _session


def encode(images,cancelled=lambda:False):
    model=session();result=[]
    for off in range(0,len(images),4):
        if cancelled():return None
        batch=np.stack([character.preprocess(im) for im in images[off:off+4]])
        v=np.asarray(model.run(None,{model.get_inputs()[0].name:batch})[0],np.float32)
        if v.shape!=(len(batch),DIM) or not np.isfinite(v).all():raise ValueError('Invalid identity refinement output')
        result.extend(v/np.maximum(np.linalg.norm(v,axis=1,keepdims=True),1e-9))
    return np.asarray(result,np.float32)


class VectorCache(perceptual.VectorCache):
    def __init__(self,thumbs,cancelled=lambda:False,force=False):
        super().__init__(thumbs,cancelled,force,identity=model_identity(),encoder=encode,
                         database='subject-identity-refine.sqlite3',dim=DIM)


def candidate_mask(ga,gb,pa,pb,sa,sb,threshold):
    if len(ga)!=len(pa) or len(ga)!=len(sa) or len(gb)!=len(pb) or len(gb)!=len(sb):
        raise ValueError('Incompatible sampled frame caches')
    semantic=float(np.interp(threshold,[.65,.72,.80],[.88,.88,.93]))
    appearance=float(np.interp(threshold,[.65,.72,.80],[.50,.50,.60]))
    return ga[:,None]&gb[None,:]&(pa@pb.T>=appearance)&(sa@sb.T>=semantic)


def verify(mask,a,b,threshold):
    if mask.shape!=(len(a),len(b)):raise ValueError('Incompatible sampled frame caches')
    # Larger CCIP has a distinct upstream distance scale (.213231 at its own
    # benchmark optimum). These more conservative joint presets are not probabilities.
    cut=float(np.interp(threshold,[.65,.72,.80],[.80,.82,.87]))
    scores=np.clip((1+a@b.T)/2,0,1);accepted=mask&(scores>=cut)
    if not accepted.any():return None
    af,bf=np.unravel_index(int(np.where(accepted,scores,-1).argmax()),scores.shape)
    score=float(scores[af,bf])
    return score,(score,int(af),int(bf)),'identity_refine'
