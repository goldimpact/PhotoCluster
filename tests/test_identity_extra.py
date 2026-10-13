from contextlib import closing
from types import SimpleNamespace
import io

import numpy as np
import pytest
from PIL import Image

from photocluster import identity_extra as extra,subject,subject_auto as auto
from test_identity_refine import vec


def test_all_signals_must_support_same_frame_and_both_domains():
    d=np.array([[.99,.01]],np.float32);x=vec()
    mask=extra.candidate_mask(d,d,x,vec(.7),x,vec(.6),x,vec(.9),.72)
    assert mask.any()
    mask=extra.large_mask(mask,x,vec(.7),.72)
    assert extra.verify(mask,x,vec(.7),x,vec(.7),.72)[2]=={'kind':'alternate_identity'}
    assert extra.verify(mask,x,vec(.6),x,vec(.7),.72) is None
    assert not extra.candidate_mask(d,np.array([[.94,.06]]),x,x,x,x,x,x,.72).any()
    mask=extra.candidate_mask(d,np.repeat(d,2,axis=0),x,np.concatenate([x,vec(-1)]),
        x,np.concatenate([vec(.3),x]),x,np.concatenate([x,x]),.72)
    assert not mask.any()


def test_encoder_preserves_upstream_preprocessing_and_cancellation(monkeypatch):
    seen=[]
    class Model:
        def get_inputs(self):return [SimpleNamespace(name='x')]
        def run(self,names,feed):seen.append(feed['x']);return [np.repeat(vec(),len(feed['x']),axis=0)]
    monkeypatch.setattr(extra,'session',lambda:Model())
    im=Image.new('RGB',(13,19),'blue')
    assert extra.encode([im]*5).shape==(5,768)
    np.testing.assert_array_equal(seen[0][0],extra.character.preprocess(im))
    assert [len(x) for x in seen]==[4,1]
    assert extra.encode([im],lambda:True) is None


def test_cache_isolation_budget_and_model_signature(tmp_path,monkeypatch):
    calls=[];version=['one'];monkeypatch.setattr(extra,'MAX_NEW_MEDIA',1)
    monkeypatch.setattr(extra,'model_identity',lambda:version[0])
    monkeypatch.setattr(extra,'encode',lambda *args:(calls.append(1) or vec()))
    monkeypatch.setattr(subject,'frames',lambda *args:[Image.new('RGB',(8,8))])
    p=dict(key='a',sha256='a');q=dict(key='b',sha256='b')
    with closing(extra.VectorCache(tmp_path)) as cache:
        assert cache.get(p) is not None and cache.get(q) is None
        assert cache.get(p) is not None and len(calls)==1
    with closing(extra.VectorCache(tmp_path)) as cache:
        assert cache.get(q) is not None
        assert cache.get(p) is not None and len(calls)==2
    first=auto.model_identity();version[0]='two';assert auto.model_identity()!=first
    with closing(extra.VectorCache(tmp_path,force=True)) as cache:
        cache.get(p);cache.memory.clear();cache.get(p)
    assert len(calls)==3 and (tmp_path/'subject-identity-extra.sqlite3').exists()


def test_installer_rejects_unverified_weights(tmp_path,monkeypatch):
    from scripts import setup_identity_extra as setup
    model=tmp_path/'extra.onnx';model.write_bytes(b'old');monkeypatch.setattr(setup,'MODEL',model)
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**kw:io.BytesIO(b'bad')))
    with pytest.raises(RuntimeError,match='checksum'):setup.install()
    assert model.read_bytes()==b'old' and not model.with_suffix('.download').exists()


def test_pipeline_extra_route_is_lazy_cancelable_and_preserves_frame_evidence(monkeypatch):
    from test_subject_auto import photos,gv,cv,prepare
    prepare(monkeypatch,[gv(0)]*4+[gv(2)],[cv(0)]*4+[cv(.85)],[np.array([True])]*5)
    for module in (auto.perceptual,auto.complementary,auto.identity_refine,auto.domain_refine,auto.local_context,extra):
        monkeypatch.setattr(module,'installed',lambda:True)
    calls=[];closed=[];stop=[False]
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):return vec()
        def close(self):closed.append(1)
    class Domain(Cache):
        def get(self,p):return np.array([[.99,.01]],np.float32)
    class Local(Cache):
        def get(self,p):return None
    class Extra(Cache):
        def get(self,p):calls.append(p['key']);return None if stop[0] else vec()
    for module in (auto.perceptual,auto.complementary,auto.identity_refine):monkeypatch.setattr(module,'VectorCache',Cache)
    monkeypatch.setattr(auto.domain_refine,'VectorCache',Domain)
    monkeypatch.setattr(auto.local_context,'VectorCache',Local)
    monkeypatch.setattr(extra,'VectorCache',Extra)
    monkeypatch.setattr(auto.complementary,'verify',lambda *a,**kw:None)
    monkeypatch.setattr(auto.domain_refine,'candidate_mask',lambda *a:np.zeros((1,1),bool))
    # Old large identity fallback must not mask the route under test.
    monkeypatch.setattr(auto.identity_refine,'verify',lambda *a:None)
    monkeypatch.setattr(extra,'verify',lambda mask,a,b,la,lb,t:(1.,(1.,0,0),{'kind':'alternate_identity'}) if mask.any() else None)
    groups=auto.cluster(photos(5),None)
    assert len(groups)==1 and len(groups[0])==5 and calls
    assert groups[0][-1]['subject_evidence']=={'kind':'alternate_identity'}
    assert len(closed)==6
    calls.clear();stop[0]=True
    assert len(auto.cluster(photos(5),None)[0])==4 and len(closed)==12
    calls.clear();monkeypatch.setattr(extra,'candidate_mask',lambda *a:np.zeros((1,1),bool))
    assert len(auto.cluster(photos(5),None)[0])==4 and not calls
