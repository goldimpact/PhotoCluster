"""Optional local DreamSim verification; lazily encode only candidate media."""
from collections import OrderedDict
from pathlib import Path
import sqlite3
import threading

import numpy as np
from PIL import Image

from .config import DATA

MODEL = DATA/'models/subject-perceptual.onnx'
VERSION = 'dreamsim-dinov2b14-prenorm-cls-bicubic224-v1'
DIM = 768
_session = None
_identity = None
_lock = threading.Lock()


def installed():
    return MODEL.is_file()


def model_identity():
    from .semantic import file_identity
    return VERSION + ':' + file_identity(MODEL)


def session():
    global _session, _identity
    identity = model_identity()
    with _lock:
        if _session is None or _identity != identity:
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = 4; options.inter_op_num_threads = 1
            # CUDA is optional; standard installations retain the CPU path.
            providers = ['CPUExecutionProvider']
            if 'CUDAExecutionProvider' in ort.get_available_providers():
                providers.insert(0, 'CUDAExecutionProvider')
            _session = ort.InferenceSession(str(MODEL), sess_options=options, providers=providers)
            _identity = identity
    return _session


def encode(images, cancelled=lambda: False):
    model = session(); result = []
    for offset in range(0, len(images), 4):
        if cancelled():return None
        batch = np.stack([np.asarray(im.convert('RGB').resize((224,224), Image.Resampling.BICUBIC), np.float32).transpose(2,0,1)/255
                          for im in images[offset:offset+4]])
        v = np.asarray(model.run(None, {model.get_inputs()[0].name: batch})[0], np.float32)
        if v.shape != (len(batch), DIM) or not np.isfinite(v).all():
            raise ValueError('Invalid perceptual model output')
        result.extend(v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9))
    return np.asarray(result, np.float32)


class VectorCache:
    def __init__(self, thumbs, cancelled=lambda: False, force=False, *, identity=None, encoder=None,
                 database='subject-perceptual.sqlite3', dim=DIM):
        self.thumbs = Path(thumbs); self.cancelled = cancelled; self.force = force
        self.identity = model_identity() if identity is None else identity
        self.encoder = encode if encoder is None else encoder; self.dim = dim
        self.memory = OrderedDict(); self.pending = 0
        self.refreshed = set()  # Keys only; force recomputes each identity once/job.
        self.con = sqlite3.connect(self.thumbs/database, timeout=30)
        self.con.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, sha TEXT, version TEXT, data BLOB)')

    def get(self, photo):
        from .frame_policy import feature_identity
        from .subject import frames
        if self.cancelled():return None
        key = photo['key']; identity = feature_identity(self.identity, photo)
        cache_key = (key, photo['sha256'], identity)
        if cache_key in self.memory:
            self.memory.move_to_end(cache_key)
            return self.memory[cache_key]
        row = None if self.force and cache_key not in self.refreshed else self.con.execute('SELECT sha,version,data FROM vectors WHERE key=?', (key,)).fetchone()
        if row and row[:2] == (photo['sha256'], identity):
            value = np.frombuffer(row[2], np.float32).reshape(-1, self.dim)
        else:
            value = self.encoder(frames(photo, self.thumbs), self.cancelled)
            if value is None:return None
            self.con.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)', (key, photo['sha256'], identity, value.tobytes()))
            if self.force:self.refreshed.add(cache_key)
            self.pending += 1
            if self.pending >= 32:self.con.commit(); self.pending = 0
        self.memory[cache_key] = value
        if len(self.memory) > 64:self.memory.popitem(last=False)
        return value

    def close(self):
        try:self.con.commit()
        finally:self.con.close()
