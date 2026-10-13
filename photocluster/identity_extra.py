"""Optional third identity encoder for rejected same-frame candidates."""
import threading

import numpy as np

from . import character, perceptual, identity_refine, local_context
from .subject_merge import Cancelled
from .config import DATA

MODEL=DATA/'models/subject-identity-extra.onnx'
VERSION='ccip-v2-caformer-s36-10-bilinear384-v1'
DIM=768
MAX_NEW_MEDIA=512
_session=None
_identity=None
_lock=threading.Lock()


def installed():
    return MODEL.is_file() and local_context.installed()


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
        if v.shape!=(len(batch),DIM) or not np.isfinite(v).all():raise ValueError('Invalid extra identity output')
        result.extend(v/np.maximum(np.linalg.norm(v,axis=1,keepdims=True),1e-9))
    return np.asarray(result,np.float32)


class VectorCache(perceptual.VectorCache):
    def __init__(self,thumbs,cancelled=lambda:False,force=False):
        self.new=0
        def bounded(images,stop):
            if stop():raise Cancelled()
            if self.new>=MAX_NEW_MEDIA:return None
            self.new+=1
            result=encode(images,stop)
            if result is None:raise Cancelled()
            return result
        super().__init__(thumbs,cancelled,force,identity=model_identity(),encoder=bounded,
                         database='subject-identity-extra.sqlite3',dim=DIM)


def candidate_mask(da,db,ca,cb,pa,pb,sa,sb,threshold):
    mask=identity_refine.candidate_mask(da[:,0]>=.95,db[:,0]>=.95,pa,pb,sa,sb,threshold)
    if mask.shape!=(len(ca),len(cb)):raise ValueError('Incompatible sampled frame caches')
    small=float(np.interp(threshold,[.65,.72,.80],[.82,.82,.85]))
    return mask & ((1+ca@cb.T)/2>=small)


def large_mask(mask,a,b,threshold):
    if mask.shape!=(len(a),len(b)):raise ValueError('Incompatible sampled frame caches')
    cut=float(np.interp(threshold,[.65,.72,.80],[.80,.82,.87]))
    return mask & ((1+a@b.T)/2>=cut)


def verify(mask,a,b,large_a,large_b,threshold):
    if mask.shape!=(len(a),len(b)):raise ValueError('Incompatible sampled frame caches')
    cut=float(np.interp(threshold,[.65,.72,.80],[.81,.83,.87]))
    accepted=mask & ((1+a@b.T)/2>=cut)
    match=identity_refine.verify(accepted,large_a,large_b,threshold)
    if match:return match[0],match[1],dict(kind='alternate_identity')
    return None
