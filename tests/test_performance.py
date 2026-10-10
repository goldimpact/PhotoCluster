import io
import json
from unittest.mock import Mock

import numpy as np
from PIL import Image

from photocluster.index import HammingIndex, PostingIndex
from photocluster.service import Service
from photocluster.vision import BKTree, LocalIndex, features
from photocluster.vision import structure, image_statistics


def test_native_hamming_is_exact():
    rng = np.random.default_rng(19)
    hashes = rng.integers(0, 2**64-1, (250,8), dtype=np.uint64)
    index, old = HammingIndex(250), BKTree()
    for i, values in enumerate(hashes):
        index.add([int(x) for x in values], i)
        for value in values:
            old.add(int(value), i)
    # Include near-boundary matches; random-only tests almost always find none.
    for radius in (0,8,12):
        for values in hashes[:10]:
            query = [int(v) ^ ((1 << radius)-1) for v in values]
            expected = {i for value in query for i in old.search(value, radius)}
            assert set(index.search(query, radius)) == expected


def test_postings_vote_rules_and_saturation():
    photos = [{'signatures':[i, 1234]} for i in range(130)]
    new, old = PostingIndex(photos), LocalIndex()
    for i in range(130):
        # Fewer than 16 candidates eliminates unspecified tied-cutoff ordering.
        if i < 15 or i > 105:
            assert set(new.search(i)) == set(old.search(photos[i]))
        new.add(i, i)
        old.add(photos[i], i)


def test_cached_scan_never_reads_phone(tmp_path, monkeypatch):
    service = Service(tmp_path)
    photo = dict(key='a',path='/storage/emulated/0/a.jpg',size=123,modified=1)
    (service.thumbs/'a.jpg').touch()
    (service.thumbs/'a.npz').touch()
    with service.connect() as con:
        con.execute('INSERT INTO features VALUES (?,?)', ('a',json.dumps({'sha256':'x'})))
        con.execute('INSERT INTO skipped VALUES (?,?)', ('b','animated'))
    reader = Mock(side_effect=AssertionError('Must not read phone'))
    monkeypatch.setattr('photocluster.service.adb.read_batch',reader)
    monkeypatch.setattr('photocluster.service.adb.read_photo',reader)
    processed,errors=[],[]
    import time
    service.scan_photos('serial',[photo,dict(photo,key='b')],processed,errors,time.perf_counter())
    assert len(processed)==1 and len(errors)==1
    reader.assert_not_called()


def test_batched_scan_fallback_and_skip_cache(tmp_path,monkeypatch):
    service = Service(tmp_path)
    raw=io.BytesIO()
    Image.new('RGB',(40,30),'red').save(raw,'PNG')
    payload=raw.getvalue()
    photos=[dict(key=k,path=f'/storage/emulated/0/{k}.png',size=len(payload),modified=1) for k in ('a','b')]
    def batch(*args):
        yield photos[0],payload
        raise RuntimeError('Connection lost')
    monkeypatch.setattr('photocluster.service.adb.read_batch',batch)
    single=Mock(return_value=payload)
    monkeypatch.setattr('photocluster.service.adb.read_photo',single)
    def extract(raw,path):
        if path.stem=='b':
            raise ValueError('动画超过分析上限（测试）')
        path.touch();path.with_suffix('.npz').touch()
        return {'sha256':'a'}
    monkeypatch.setattr('photocluster.service.vision.features',extract)
    processed,errors=[],[]
    import time
    service.scan_photos('s',photos,processed,errors,time.perf_counter())
    assert single.call_count==1
    assert len(processed)==1 and len(errors)==1
    with service.connect() as con:
        assert con.execute('SELECT count(*) FROM skipped').fetchone()[0]==0
    assert errors[0]['key']=='b'  # A failed media item remains renderable as a card.


def test_draft_preserves_original_dimensions_and_exif(tmp_path):
    raw=io.BytesIO()
    img=Image.new('RGB',(2400,1600),'blue')
    exif=Image.Exif();exif[274]=6
    img.save(raw,'JPEG',exif=exif)
    result=features(raw.getvalue(),tmp_path/'draft.jpg')
    assert (result['width'],result['height'])==(1600,2400)
    with Image.open(tmp_path/'draft.jpg') as preview:
        assert preview.height==640 and preview.width<preview.height


def test_reused_image_statistics_preserve_score():
    rng=np.random.default_rng(5)
    a=rng.integers(0,256,(64,64,3),dtype=np.uint8)
    b=np.roll(a,1,axis=0)
    mask=np.ones((64,64),bool);mask[:5]=False
    original=structure(a,b,mask)
    optimized=structure(a,b,mask,target_stats=image_statistics(b))
    assert np.allclose(original,optimized,atol=1e-7)


def test_identical_scan_reuses_matches(tmp_path,monkeypatch):
    service=Service(tmp_path)
    p=dict(key='a',sha256='hash',size=123,path='/storage/emulated/0/a.jpg')
    def scan(serial,photos,processed,errors,started):
        processed.extend(photos)
    monkeypatch.setattr(service,'scan_photos',scan)
    match=Mock(return_value=[])
    monkeypatch.setattr('photocluster.service.vision.cluster',match)
    service.worker('s',[p],'strong','all')
    service.worker('s',[p],'strong','all')
    assert match.call_count==1
    service.worker('s',[p],'relaxed','all')
    assert match.call_count==2
    service.worker('s',[dict(p,key='changed')],'relaxed','all')
    assert match.call_count==3


def test_native_descriptor_matcher_equals_brute_force():
    import cv2
    from photocluster.vision import descriptor_matches
    rng=np.random.default_rng(42)
    a=rng.integers(0,256,(90,128)).astype(np.float32)
    b=np.concatenate([a[:30],rng.integers(0,256,(60,128)).astype(np.float32)])
    b[0]=b[1]  # Include a tied best-neighbor distance.
    reference=cv2.BFMatcher(cv2.NORM_L2SQR).knnMatch(a,b,k=2)
    expected={(m.queryIdx,m.trainIdx,m.distance) for m,n in reference if m.distance<.72**2*n.distance}
    actual={(m.queryIdx,m.trainIdx,m.distance) for m in descriptor_matches(a,b)}
    assert expected==actual


def test_tar_stream_preserves_special_names_and_rejects_changed_size(monkeypatch):
    import tarfile
    from photocluster import adb
    archive=io.BytesIO()
    name="storage/emulated/0/中文/it's a photo.jpg"
    with tarfile.open(fileobj=archive,mode='w') as tar:
        member=tarfile.TarInfo(name);member.size=3
        tar.addfile(member,io.BytesIO(b'abc'))
        member=tarfile.TarInfo('storage/emulated/0/changed.jpg');member.size=4
        tar.addfile(member,io.BytesIO(b'abcd'))
    process=Mock(stdout=io.BytesIO(archive.getvalue()),stderr=io.BytesIO(),poll=lambda:0)
    launch=Mock(return_value=process)
    monkeypatch.setattr('photocluster.adb.subprocess.Popen',launch)
    photos=[dict(path='/'+name,size=3),dict(path='/storage/emulated/0/changed.jpg',size=3)]
    result=list(adb.read_batch('serial',photos))
    assert result==[(photos[0],b'abc')]
    assert ' -C / -- ' in launch.call_args.args[0][-1]
    assert launch.call_args.args[0][-1].endswith('2>/dev/null')
