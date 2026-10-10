import io
import json
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image,ImageDraw

from photocluster import adb,media,semantic,vision
from photocluster.service import Service


def test_semantic_group_cross_formats_without_time_alignment(tmp_path,monkeypatch):
    vectors={
        'still':np.array([[1.,0.,0.]],np.float32),
        'gif':np.array([[0.,1.,0.],[.99,.1,0.]],np.float32),
        'video':np.array([[0.,0.,1.],[.98,.15,0.]],np.float32),
        'other':np.array([[0.,0.,1.]],np.float32)}
    for key,value in vectors.items():vectors[key]=value/np.linalg.norm(value,axis=1,keepdims=True)
    # CLIP supplies 512 dimensions; pad this controlled retrieval fixture.
    vectors={k:np.pad(v,((0,0),(0,509))) for k,v in vectors.items()}
    monkeypatch.setattr(semantic,'ensure_embeddings',lambda p,*args:vectors[p['key']])
    photos=[dict(key=k,sha256=k,album='/a',size=100,width=100-i,height=100,sharpness=10,
                 media_type='video' if k=='video' else 'image',animated=k=='gif') for i,k in enumerate(vectors)]
    groups=semantic.cluster(photos,tmp_path,threshold=.9)
    assert {p['key'] for p in groups[0]}=={'still','gif','video'}
    assert all(p.get('relation')=='content' for p in groups[0][1:])


def test_sync_progress_pollable_during_adb_io(tmp_path,monkeypatch):
    service=Service(tmp_path);entered=threading.Event();release=threading.Event()
    def inventory(serial):entered.set();release.wait(5);return []
    monkeypatch.setattr(adb,'inventory',inventory)
    worker=threading.Thread(target=service.refresh,args=('s',));worker.start();assert entered.wait(1)
    assert service.lock.acquire(timeout=.2)
    try:assert service.sync_status['running'] and service.sync_status['phase']=='reading'
    finally:service.lock.release();release.set();worker.join(2)
    assert service.sync_status['phase']=='done'


def test_video_inventory_includes_unknown_dimensions(monkeypatch):
    image='Row: 0 _id=1, _data=/storage/emulated/0/a.jpg, _size=5, date_modified=1, width=10, height=10, bucket_id=1, bucket_display_name=a, datetaken=NULL'
    video='Row: 0 _id=2, _data=/storage/emulated/0/b.ts, _size=5, date_modified=1, width=NULL, height=NULL, bucket_id=1, bucket_display_name=a, datetaken=NULL'
    monkeypatch.setattr(adb,'run',lambda args: (video if '/video/' in args[-1] else image).encode())
    photos=adb.inventory('s');assert len(photos)==2
    assert photos[1]['media_type']=='video' and photos[1]['width']==0


def test_video_keyframes_and_partial_gif_recovery(tmp_path):
    import shutil
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg not installed')
    video=tmp_path/'video.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=10','-t','1',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    feature=media.file_features(video,tmp_path/'video.jpg',video=True)
    assert feature['media_type']=='video' and feature['sample_count']>=6
    assert feature['duration_ms']>=900 and Path(feature['frame_path']).exists()
    frames=[]
    for i in range(6):
        frame=Image.new('RGB',(80,60),'white');ImageDraw.Draw(frame).rectangle((i*4,5,i*4+25,40),fill='red');frames.append(frame)
    raw=io.BytesIO();frames[0].save(raw,'GIF',save_all=True,append_images=frames[1:],duration=100,loop=0)
    recovered=media.recover_animation(raw.getvalue()[:-30],tmp_path/'recovered.jpg','truncated test')
    assert recovered['partial'] and recovered['sample_count']>0


def test_local_encoder_actual_model_and_cache(tmp_path):
    if not semantic.MODEL.exists():pytest.skip('Model not installed')
    image=Image.new('RGB',(300,250),'white');ImageDraw.Draw(image).ellipse((20,20,180,180),fill='red')
    image.save(tmp_path/'k.jpg');photo=dict(key='k',sha256='v1')
    a=semantic.ensure_embeddings(photo,tmp_path);assert a.shape==(1,512)
    assert abs(np.linalg.norm(a)-1)<1e-5
    b=semantic.ensure_embeddings(photo,tmp_path);assert np.array_equal(a,b)


def test_real_encoder_shared_frame_across_media_types(tmp_path):
    if not semantic.MODEL.exists():pytest.skip('Model not installed')
    first=Image.new('RGB',(256,256),'white');draw=ImageDraw.Draw(first)
    draw.rectangle((35,30,160,180),fill='red');draw.ellipse((110,110,240,240),fill='blue')
    second=first.rotate(7,fillcolor='white');third=first.resize((160,256)).resize((256,256))
    vectors=semantic.embeddings([first,second,third])
    image=vectors[:1];gif=vectors[1:];video=vectors[[2,0]]
    assert semantic.similarity(image,gif)[0]>.84
    assert semantic.similarity(gif,video)[0]>.84


def test_video_lease_deletes_temp_on_release(monkeypatch):
    from photocluster.video import VideoLeases
    leases=VideoLeases()
    monkeypatch.setattr(adb,'pull_file',lambda serial,remote,path:Path(path).write_bytes(b'video'))
    token=leases.create('s',dict(path='/storage/emulated/0/a.mp4',size=5))
    path=leases.get(token);assert path.exists()
    leases.release(token);assert not path.exists() and leases.get(token) is None


def test_partial_media_kept_as_review_card(tmp_path,monkeypatch):
    service=Service(tmp_path)
    p=dict(key='p',path='/storage/emulated/0/partial.gif',sha256='hash',size=10,warning='recovered frames',partial=True)
    monkeypatch.setattr(service,'scan_photos',lambda serial,photos,processed,errors,started:processed.extend(photos))
    monkeypatch.setattr(vision,'cluster',lambda *args,**kwargs:[])
    service.worker('s',[p],'strong','all')
    issues=service.read_json('errors.json',[])
    assert issues[0]['key']=='p' and issues[0]['analyzed']


def test_content_sort_size_and_timestamp_api(tmp_path,monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    module=importlib.import_module('photocluster.app');service=Service(tmp_path)
    service.result=dict(summary={},groups=[
        dict(id=1,kind='content',potential_bytes=0,photos=[dict(path='/a',size=10,taken=0,modified=20)]),
        dict(id=2,kind='content',potential_bytes=0,photos=[dict(path='/b',size=100,taken=5,modified=30)])])
    monkeypatch.setattr(module,'service',service)
    with TestClient(module.app) as client:
        assert client.get('/api/groups?sort=size').json()['groups'][0]['id']==2
        assert client.get('/api/groups?sort=newest').json()['groups'][0]['id']==1
        assert client.get('/api/groups?sort=oldest').json()['groups'][0]['id']==2
