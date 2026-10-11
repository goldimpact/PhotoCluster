import json
import time

import numpy as np
import pytest
from PIL import Image

from photocluster import character, frame_policy, semantic, subject, subject_auto
from photocluster.service import Service


def test_incremental_scan_upgrades_only_legacy_or_missing_dynamic_frames(tmp_path, monkeypatch):
    service = Service(tmp_path)
    photos = [dict(key=k, path=f'/storage/emulated/0/{k}.gif', size=3) for k in ('legacy', 'current', 'missing', 'still')]
    for p in photos:
        (service.thumbs/(p['key']+'.jpg')).touch()
        (service.thumbs/(p['key']+'.npz')).touch()
        value = dict(sha256='unchanged')
        if p['key'] != 'still':value['animated'] = True
        if p['key'] in ('current', 'missing'):
            value.update(media_version=2, frame_path=str(service.thumbs/(p['key']+'.frames.npz')))
        if p['key'] == 'current':(service.thumbs/'current.frames.npz').touch()
        with service.connect() as con:
            con.execute('INSERT INTO features VALUES (?,?)', (p['key'], json.dumps(value)))
    requested = []
    def read(serial, batch):
        requested.extend(p['key'] for p in batch)
        yield from ((p, b'gif') for p in batch)
    def extract(raw, thumb):
        path = thumb.with_suffix('.frames.npz'); path.touch()
        return dict(sha256='unchanged', animated=True, media_version=2, frame_path=str(path))
    monkeypatch.setattr('photocluster.service.adb.read_batch', read)
    monkeypatch.setattr('photocluster.service.vision.features', extract)
    processed, errors = [], []
    service.scan_photos('mock', photos, processed, errors, time.perf_counter())
    assert requested == ['legacy', 'missing'] and not errors
    assert all(not frame_policy.needs_refresh(p) for p in processed)
    requested.clear(); processed.clear()
    service.scan_photos('mock', photos, processed, errors, time.perf_counter())
    assert not requested and len(processed) == 4


@pytest.mark.parametrize('module,shape', [(subject, (1,6,384)), (character, (1,768))])
def test_frame_upgrade_invalidates_subject_vectors_without_sha_change(tmp_path, monkeypatch, module, shape):
    calls = []
    monkeypatch.setattr(module, 'model_identity', lambda: 'same-model')
    monkeypatch.setattr(subject, 'frames', lambda *a: [Image.new('RGB', (10,10))])
    monkeypatch.setattr(module, 'encode', lambda ims: (calls.append(True) or np.zeros(shape, np.float32)))
    p = dict(key='a', sha256='same-sha', animated=True)
    module.vectors([p], tmp_path, None, lambda: False, False)
    module.vectors([p], tmp_path, None, lambda: False, False)
    assert len(calls) == 1
    path = tmp_path/'a.frames.npz'; path.touch()
    p.update(media_version=2, frame_path=str(path))
    module.vectors([p], tmp_path, None, lambda: False, False)
    assert len(calls) == 2
    module.vectors([p], tmp_path, None, lambda: False, False)
    assert len(calls) == 2


def test_frame_upgrade_invalidates_router_and_clip_both_cache_layers(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subject_auto, 'routing_identity', lambda: 'router')
    monkeypatch.setattr(subject, 'frames', lambda *a: [Image.new('RGB', (10,10))])
    monkeypatch.setattr(subject_auto, 'routing_scores', lambda *a: (calls.append('route') or np.zeros((1,5), np.float32)))
    monkeypatch.setattr(semantic, 'model_identity', lambda: 'clip')
    monkeypatch.setattr(semantic, 'frame_images', lambda *a: [Image.new('RGB', (10,10))])
    monkeypatch.setattr(semantic, 'embeddings', lambda *a: (calls.append('clip') or np.zeros((1,512), np.float32)))
    p = dict(key='a', sha256='same', animated=True)
    def load():
        subject_auto.load_routes([p], tmp_path, None, lambda: False, False)
        semantic.load_vectors([p], tmp_path, None, lambda: False, False)
    load(); load()
    assert calls == ['route', 'clip']
    path = tmp_path/'a.frames.npz'; path.touch()
    p.update(media_version=2, frame_path=str(path))
    load(); load()
    assert calls == ['route', 'clip', 'route', 'clip']


def test_frame_upgrade_invalidates_geometry_pair_and_final_result(tmp_path, monkeypatch):
    from photocluster.pair_cache import PairCache
    service = Service(tmp_path)
    p = dict(key='a', sha256='same', animated=True)
    monkeypatch.setattr(service, 'scan_photos', lambda serial, photos, processed, *a: processed.extend(photos))
    monkeypatch.setattr(subject_auto, 'model_identity', lambda: 'unchanged-policy')
    calls = []
    monkeypatch.setattr(subject_auto, 'cluster', lambda *a: (calls.append(True) or []))
    service.worker('mock', [p], 'subject', 'all', subject_engine='auto')
    service.worker('mock', [p], 'subject', 'all', subject_engine='auto')
    assert len(calls) == 1
    cache = PairCache(tmp_path/'pairs.sqlite3', 'same-rules')
    old_identity = cache.identity(p)
    path = tmp_path/'a.frames.npz'; path.touch()
    p.update(media_version=2, frame_path=str(path))
    assert cache.identity(p) != old_identity
    cache.close()
    service.worker('mock', [p], 'subject', 'all', subject_engine='auto')
    assert len(calls) == 2


def test_still_image_feature_identity_stays_compatible():
    assert frame_policy.feature_identity('existing-model', dict(key='still')) == 'existing-model'


def test_sampling_upgrade_replaces_variant_frames_and_memory_cache(tmp_path, monkeypatch):
    from photocluster import variants
    monkeypatch.setattr(variants.vision, 'comparison_image', lambda *a: np.zeros((384,384,3), np.uint8))
    photo = dict(key='a', sha256='same', animated=True, feature_path=str(tmp_path/'a.npz'))
    old = variants.prepare(photo)
    assert not variants.frame_image(old['variant_path'], 0).any()
    frames = tmp_path/'a.frames.npz'
    np.savez_compressed(frames, frames=np.full((1,256,256,3), 255, np.uint8))
    photo.update(frame_path=str(frames), media_version=2)
    new = variants.prepare(photo)
    assert new['variant_path'] == old['variant_path']
    assert variants.frame_image(new['variant_path'], 0).min() == 255
