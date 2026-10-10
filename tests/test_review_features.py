import hashlib
import importlib
import io
import json
import time
from unittest.mock import Mock

import numpy as np
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from photocluster import vision, adb
from photocluster.service import Service


def gif_bytes(size=(160,120), changed=False, durations=None, rotate=False):
    frames=[]
    for i in range(8):
        frame=Image.new('RGB',(160,120),'white')
        draw=ImageDraw.Draw(frame)
        draw.rectangle((10+i*9,20,40+i*9,80), fill='red' if not changed or i==0 else 'blue')
        draw.text((3,100), 'animated sample', fill='black')
        if rotate:frame=frame.rotate(90,expand=True)
        else:frame=frame.resize(size)
        frames.append(frame)
    buffer=io.BytesIO()
    frames[0].save(buffer,'GIF',save_all=True,append_images=frames[1:],duration=durations or [100]*8,loop=0,disposal=2)
    return buffer.getvalue()


def test_gif_timeline_resize_rotation_and_different_motion(tmp_path):
    a=vision.features(gif_bytes(),tmp_path/'a.jpg')
    assert a['animated'] and a['frames']==8 and a['duration_ms']==800
    assert len(a['animation_samples'])==12
    for name,raw in [('resize',gif_bytes((80,60))),('rotate',gif_bytes(rotate=True))]:
        b=vision.features(raw,tmp_path/(name+'.jpg'))
        assert vision.compare(a,b,'strong') is not None
        photos=[dict(x,size=100,album='/a') for x in (a,b)]
        assert len(vision.cluster(photos,'strong'))==1
    changed=vision.features(gif_bytes(changed=True),tmp_path/'changed.jpg')
    assert vision.compare(a,changed,'strong') is None
    with Image.open(io.BytesIO(gif_bytes())) as src:
        out=io.BytesIO();src.convert('RGB').save(out,'PNG')
    still=vision.features(out.getvalue(),tmp_path/'still.jpg')
    assert vision.compare(a,still,'strong') is None
    slow=vision.features(gif_bytes(durations=[400]*8),tmp_path/'slow.jpg')
    assert vision.compare(a,slow,'strong') is None


def test_media_dates():
    base='Row: 0 _id=1, _data=/storage/emulated/0/a.jpg, _size=10, date_modified=1700000000, width=40, height=30, bucket_id=1, bucket_display_name=a'
    assert adb.parse_inventory(base+', datetaken=1600000000123')[0]['taken']==1600000000.123
    assert adb.parse_inventory(base+', datetaken=NULL')[0]['taken']==0
    assert adb.parse_inventory(base)[0]['taken']==0


def test_original_in_memory_and_changed_file(monkeypatch,tmp_path):
    module=importlib.import_module('photocluster.app')
    service=Service(tmp_path)
    raw=gif_bytes()
    photo=dict(key='a',path='/storage/emulated/0/a.gif',size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    service.catalog=dict(serial='s',photos=[photo])
    service.result=dict(summary={'serial':'s'},groups=[dict(id=1,photos=[photo])])
    monkeypatch.setattr(module,'service',service)
    monkeypatch.setattr(module.adb,'read_photo',lambda *args:raw)
    before=set(tmp_path.rglob('*'))
    with TestClient(module.app) as client:
        r=client.get('/api/original/a')
        assert r.content==raw and r.headers['content-type']=='image/gif'
        assert 'no-store' in r.headers['cache-control']
        assert client.get('/api/original/missing').status_code==404
        monkeypatch.setattr(module.adb,'read_photo',lambda *args:b'x'*len(raw))
        assert client.get('/api/original/a').status_code==409
    assert not (set(tmp_path.rglob('*'))-before)


def test_sort_filter_and_search(monkeypatch,tmp_path):
    module=importlib.import_module('photocluster.app')
    service=Service(tmp_path)
    service.result=dict(summary={},groups=[
        dict(id=1,potential_bytes=10,photos=[dict(path='/a/old.gif',taken=100,modified=500,animated=True)]),
        dict(id=2,potential_bytes=20,photos=[dict(path='/b/new.jpg',taken=0,modified=200)])])
    monkeypatch.setattr(module,'service',service)
    with TestClient(module.app) as client:
        assert client.get('/api/groups?sort=newest').json()['groups'][0]['id']==2
        assert client.get('/api/groups?sort=oldest').json()['groups'][0]['id']==1
        assert client.get('/api/groups?sort=size').json()['groups'][0]['id']==2
        assert client.get('/api/groups?kind=animated').json()['total']==1
        assert client.get('/api/groups?q=NEW.JPG').json()['total']==1


def test_force_rereads_cached_file_and_clears_failure(tmp_path,monkeypatch):
    service=Service(tmp_path)
    p=dict(key='k',path='/storage/emulated/0/a.jpg',size=3)
    (service.thumbs/'k.jpg').touch();(service.thumbs/'k.npz').touch()
    with service.connect() as con:
        con.execute('INSERT INTO features VALUES (?,?)',('k',json.dumps({'sha256':'old'})))
    monkeypatch.setattr(adb,'read_batch',lambda *args:((photo,raw) for photo,raw in [(p,b'new')]))
    monkeypatch.setattr(vision,'features',lambda *args:dict(sha256='new'))
    processed=[];errors=[]
    service.scan_photos('s',[p],processed,errors,time.perf_counter(),force=True)
    assert processed[0]['sha256']=='new'
    monkeypatch.setattr(vision,'features',Mock(side_effect=ValueError('decode failed')))
    service.scan_photos('s',[p],[],[],time.perf_counter(),force=True)
    with service.connect() as con:
        assert con.execute('SELECT count(*) FROM features').fetchone()[0]==0


def test_scan_synchronizes_and_includes_new_album(tmp_path,monkeypatch):
    service=Service(tmp_path)
    service.catalog=dict(serial='s',photos=[])
    photo=dict(path='/storage/emulated/0/new/a.jpg',size=3,modified=1,album='/storage/emulated/0/new',album_name='new')
    inventory=Mock(return_value=[photo]);monkeypatch.setattr(adb,'inventory',inventory)
    worker=Mock();monkeypatch.setattr(service,'worker',worker)
    service.status['running']=True
    service.scan_request('s',[],'strong','all',0,False,True)
    inventory.assert_called_once_with('s')
    assert worker.call_args.args[1][0]['path']==photo['path']


def test_upgrade_retries_previously_skipped_gifs(tmp_path):
    service=Service(tmp_path)
    with service.connect() as con:
        con.execute('INSERT INTO skipped VALUES (?,?)',('gif','动态图片暂不比较，避免只比较第一帧'))
    upgraded=Service(tmp_path)
    with upgraded.connect() as con:
        assert con.execute('SELECT count(*) FROM skipped').fetchone()[0]==0


def test_force_ignores_matching_result_cache(tmp_path,monkeypatch):
    service=Service(tmp_path)
    p=dict(key='a',sha256='hash',size=123,path='/storage/emulated/0/a.jpg')
    def scan(serial,photos,processed,errors,started,force=False):
        processed.extend(photos)
    monkeypatch.setattr(service,'scan_photos',scan)
    match=Mock(return_value=[]);monkeypatch.setattr(vision,'cluster',match)
    service.worker('s',[p],'strong','all')
    service.worker('s',[p],'strong','all',force=True)
    assert match.call_count==2


def test_original_conversion_keeps_full_resolution(monkeypatch,tmp_path):
    module=importlib.import_module('photocluster.app');service=Service(tmp_path)
    out=io.BytesIO();Image.new('RGB',(900,700),'green').save(out,'TIFF');raw=out.getvalue()
    service.catalog=dict(serial='s',photos=[dict(key='tiff',path='/storage/emulated/0/a.tiff',size=len(raw))])
    monkeypatch.setattr(module,'service',service);monkeypatch.setattr(adb,'read_photo',lambda *args:raw)
    with TestClient(module.app) as client:
        r=client.get('/api/original/tiff');assert r.status_code==200
        assert r.headers['x-preview-converted']=='1'
        with Image.open(io.BytesIO(r.content)) as decoded:
            assert decoded.size==(900,700) and decoded.format=='PNG'


def test_animation_timeline_respects_duration(tmp_path):
    # Same visual timeline with duplicated frames/reencoded frame delays.
    original=gif_bytes(durations=[50,150,50,150,50,150,50,150])
    frames=[];durations=[]
    with Image.open(io.BytesIO(original)) as source:
        for i in range(source.n_frames):
            source.seek(i);frames.append(source.copy());durations.append(source.info['duration'])
    stream=io.BytesIO()
    frames[0].save(stream,'GIF',save_all=True,append_images=frames[1:],duration=durations,loop=1,disposal=2)
    a=vision.features(original,tmp_path/'a.jpg');b=vision.features(stream.getvalue(),tmp_path/'b.jpg')
    assert a['sha256']!=b['sha256']
    assert vision.compare(a,b,'strong') is not None
