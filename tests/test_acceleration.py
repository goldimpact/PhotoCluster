import json
import numpy as np
import pytest
from unittest.mock import Mock

from photocluster import acceleration,semantic,vision
from photocluster.service import Service


def test_gpu_exact_descriptor_parity():
    if acceleration.cuda() is None:pytest.skip('CUDA optional')
    rng=np.random.default_rng(19);pairs=[]
    for n in (14,90,350,600):
        a=rng.integers(0,256,(n,128)).astype(np.float32)
        b=np.concatenate([a[:10],rng.integers(0,256,(n+3,128)).astype(np.float32)])
        b[0]=b[1]  # Tied nearest neighbours fail the ratio test identically.
        pairs.append((a,b))
    actual=acceleration.descriptor_batch(pairs)
    assert actual is not None
    for pair,matches in zip(pairs,actual):
        expected=vision.descriptor_matches(*pair)
        assert [(m.queryIdx,m.trainIdx,m.distance) for m in matches]==[(m.queryIdx,m.trainIdx,m.distance) for m in expected]


def test_gpu_retrieval_matches_cpu_groups(monkeypatch,tmp_path):
    if acceleration.cuda() is None:pytest.skip('CUDA optional')
    rng=np.random.default_rng(51)
    source=rng.normal(size=(40,512)).astype(np.float32);source/=np.linalg.norm(source,axis=1,keepdims=True)
    vectors={str(i):np.stack([source[i%40],source[(i+3)%40]]) for i in range(150)}
    photos=[dict(key=str(i),sha256=str(i),album='/a' if i%2 else '/b',size=1,width=200-i,height=1,sharpness=1) for i in range(150)]
    monkeypatch.setattr(semantic,'ensure_embeddings',lambda p,*args:vectors[p['key']])
    normalize=lambda groups:[[(p['key'],p['score']) for p in g] for g in groups]
    for scope in ('all','album'):
        gpu=semantic.cluster(photos,tmp_path,scope=scope,threshold=.9)
        with monkeypatch.context() as patch:
            patch.setattr(acceleration,'cuda',lambda:None)
            cpu=semantic.cluster(photos,tmp_path,scope=scope,threshold=.9)
        assert normalize(gpu)==normalize(cpu)


def test_bulk_embedding_cache_invalidates_sha_and_force(tmp_path,monkeypatch):
    photo=dict(key='a',sha256='first')
    encode=Mock(return_value=np.ones((1,512),np.float32))
    monkeypatch.setattr(semantic,'ensure_embeddings',encode)
    load=lambda p,force=False:semantic.load_vectors([p],tmp_path,None,lambda:False,force)
    load(photo);load(photo);assert encode.call_count==1
    load(dict(photo,sha256='second'));assert encode.call_count==2
    load(dict(photo,sha256='second'),True);assert encode.call_count==3


def test_mode_switch_reuses_own_result_cache(tmp_path,monkeypatch):
    s=Service(tmp_path);photo=dict(key='k',sha256='sha',size=1)
    monkeypatch.setattr(s,'scan_photos',lambda serial,photos,processed,errors,started:processed.extend(photos))
    match=Mock(return_value=[]);monkeypatch.setattr(vision,'cluster',match)
    for mode in ('strong','relaxed','strong'):s.worker('s',[photo],mode,'all')
    assert s.status['phase']=='done' and match.call_count==2


def test_gpu_failure_falls_back_without_losing_candidates(monkeypatch,tmp_path):
    rng=np.random.default_rng(3);v=rng.normal(size=(1,512)).astype(np.float32);v/=np.linalg.norm(v)
    photos=[dict(key=str(i),sha256=str(i),width=200-i,height=1,sharpness=1,size=1,album='/a') for i in range(130)]
    monkeypatch.setattr(semantic,'ensure_embeddings',lambda *args:v)
    monkeypatch.setattr(acceleration,'cuda',lambda:True)
    class Broken:
        def __init__(self,*args):pass
        def candidates(self,*args):raise RuntimeError('GPU disconnected')
    monkeypatch.setattr(acceleration,'FrameSearch',Broken)
    groups=semantic.cluster(photos,tmp_path)
    assert len(groups)==1 and len(groups[0])==130
