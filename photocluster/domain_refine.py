"""Optional domain evidence for conservative, same-frame identity review.

The style router's not_painting label includes screenshots and promotional art.
This separate classifier can support a missed domain or exclude confidently
real photographs from the specialist route, but never establishes identity.
Positive supplemental matches still require both identity encoders and
semantic/perceptual evidence to agree.
"""
import threading

import numpy as np
from PIL import Image

from .config import DATA
from . import perceptual, identity_refine

MODEL=DATA/'models/subject-domain-refine.onnx'
VERSION='anime-real-mobilenetv3-v14-bilinear-half384-v1'
_session=None
_identity=None
_lock=threading.Lock()


def installed():
    return MODEL.is_file()


def exclude_confident_real(style_gate,scores):
    """Style's 3d label includes photographed objects, not just drawn characters.

    Only explicit high-confidence real-domain evidence disables this specialist.
    It does not accept an identity or widen general matching thresholds.
    """
    if scores.shape!=(len(style_gate),2):raise ValueError('Incompatible sampled frame caches')
    return style_gate & (scores[:,1]<.90)


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
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _identity=identity
    return _session


def encode(images,cancelled=lambda:False):
    model=session();result=[]
    for image in images:
        if cancelled():return None
        # Upstream labels: anime, real. Preserve probabilities, not unit vectors.
        x=(np.asarray(image.convert('RGB').resize((384,384),Image.Resampling.BILINEAR),np.float32)/255-.5)/.5
        value=np.asarray(model.run(['output'],{model.get_inputs()[0].name:x.transpose(2,0,1)[None]})[0],np.float32)
        if value.shape!=(1,2) or not np.isfinite(value).all() or (value<0).any() or (value>1).any():
            raise ValueError('Invalid domain refinement output')
        result.append(value[0])
    return np.asarray(result,np.float32).reshape(-1,2)


class VectorCache(perceptual.VectorCache):
    def __init__(self,thumbs,cancelled=lambda:False,force=False):
        super().__init__(thumbs,cancelled,force,identity=model_identity(),encoder=encode,
                         database='subject-domain-refine.sqlite3',dim=2)


def candidate_mask(ga,gb,pa,pb,sa,sb,threshold):
    """Cheap prefilter before loading either domain or missing identity features."""
    mask=identity_refine.candidate_mask(np.ones(len(ga),bool),np.ones(len(gb),bool),pa,pb,sa,sb,threshold)
    return mask & ~(ga[:,None]&gb[None,:])


def routed_mask(mask,a,b):
    if a.shape!=(mask.shape[0],2) or b.shape!=(mask.shape[1],2):
        raise ValueError('Incompatible sampled frame caches')
    return mask & (a[:,0,None]>=.90) & (b[None,:,0]>=.90)


def identity_mask(mask,a,b,threshold):
    if mask.shape!=(len(a),len(b)):raise ValueError('Incompatible sampled frame caches')
    cut=float(np.interp(threshold,[.65,.72,.80],[.85,.87,.91]))
    return mask & ((1+a@b.T)/2>=cut)
