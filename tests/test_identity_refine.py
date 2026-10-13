from types import SimpleNamespace
import io

import numpy as np
import pytest
from PIL import Image

from photocluster import identity_refine as refine, subject,subject_auto as auto,complementary


@pytest.fixture(autouse=True)
def without_optional_domain_export(monkeypatch):
    monkeypatch.setattr(auto.domain_refine,'installed',lambda:False)


def vec(cosine=1):
    v=np.zeros((1,768),np.float32);v[0,:2]=cosine,np.sqrt(max(0,1-cosine*cosine));return v


def test_same_frame_candidate_gate_and_separate_model_distance_scale():
    on=np.array([True]);off=np.array([False]);a=vec()
    mask=refine.candidate_mask(on,on,a,vec(.6),a,vec(.9),.72)
    assert mask.any() and refine.verify(mask,a,vec(.66),.72)
    assert refine.verify(mask,a,vec(.6),.72) is None
    assert not refine.candidate_mask(on,off,a,a,a,a,.72).any()
    mask=refine.candidate_mask(on,np.array([True,True]),a,np.concatenate([vec(.4),vec(.9)]),a,
                               np.concatenate([vec(.99),vec(.8)]),.72)
    assert not mask.any()
    with pytest.raises(ValueError):refine.verify(mask,a,a,.72)


def test_encoder_reuses_upstream_preprocessing_and_bounded_batches(monkeypatch):
    batches=[]
    class Model:
        def get_inputs(self):return [SimpleNamespace(name='x')]
        def run(self,names,feed):batches.append(feed['x']);return [np.repeat(vec(),len(feed['x']),axis=0)]
    monkeypatch.setattr(refine,'session',lambda:Model())
    image=Image.new('RGB',(12,8),'red')
    assert refine.encode([image]*5).shape==(5,768)
    np.testing.assert_array_equal(batches[0][0],refine.character.preprocess(image))
    assert [len(x) for x in batches]==[4,1]
    assert refine.encode([image],lambda:True) is None


def test_separate_cache_and_model_signature(tmp_path,monkeypatch):
    version=['one'];calls=[]
    monkeypatch.setattr(refine,'model_identity',lambda:version[0])
    monkeypatch.setattr(refine,'encode',lambda *a:(calls.append(1) or vec()))
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(8,8))])
    p=dict(key='a',sha256='sha');cache=refine.VectorCache(tmp_path)
    cache.get(p);cache.get(p);cache.close();assert len(calls)==1
    first=auto.model_identity();version[0]='two';assert auto.model_identity()!=first
    cache=refine.VectorCache(tmp_path);cache.get(p);cache.close();assert len(calls)==2
    assert (tmp_path/'subject-identity-refine.sqlite3').exists()
    assert not (tmp_path/'subject-perceptual.sqlite3').exists()


def test_refinement_is_lazy_and_closes_without_candidates(monkeypatch):
    from test_subject_auto import photos,gv,cv,prepare
    prepare(monkeypatch,[gv(0),gv(.1)],[cv(0)]*2,[np.array([True])]*2)
    monkeypatch.setattr(auto.perceptual,'installed',lambda:True)
    monkeypatch.setattr(complementary,'installed',lambda:True)
    monkeypatch.setattr(refine,'installed',lambda:True)
    closed=[]
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):return vec()
        def close(self):closed.append(1)
    class RefineCache(Cache):
        def get(self,p):pytest.fail('No failed candidate: no expensive extraction')
    monkeypatch.setattr(auto.perceptual,'VectorCache',Cache)
    monkeypatch.setattr(complementary,'VectorCache',Cache)
    monkeypatch.setattr(refine,'VectorCache',RefineCache)
    assert len(auto.cluster(photos(2),None)[0])==2
    assert len(closed)==3


def test_installer_rejects_bad_weights(tmp_path,monkeypatch):
    from scripts import setup_identity_refine as setup
    model=tmp_path/'model.onnx';model.write_bytes(b'old');monkeypatch.setattr(setup,'MODEL',model)
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:io.BytesIO(b'bad')))
    with pytest.raises(RuntimeError,match='checksum'):setup.install()
    assert model.read_bytes()==b'old' and not model.with_suffix('.download').exists()


def test_failed_complement_extracts_larger_features_only_after_candidate_gate(monkeypatch):
    from test_subject_auto import photos,gv,cv,prepare
    ps=photos(4)
    prepare(monkeypatch,[gv(0),gv(2),gv(.1),gv(2.1)],
            [cv(0),cv(2),cv(.1),cv(2.1)],[np.array([True])]*4)
    monkeypatch.setattr(auto.perceptual,'installed',lambda:True)
    monkeypatch.setattr(complementary,'installed',lambda:True)
    monkeypatch.setattr(refine,'installed',lambda:True)
    calls=[];closed=[]
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):return vec()
        def close(self):closed.append(1)
    class RefineCache(Cache):
        def get(self,p):calls.append(p['key']);return vec()
    monkeypatch.setattr(auto.perceptual,'VectorCache',Cache)
    monkeypatch.setattr(complementary,'VectorCache',Cache)
    monkeypatch.setattr(refine,'VectorCache',RefineCache)
    monkeypatch.setattr(complementary,'verify',lambda *a:None)
    groups=auto.cluster(ps,None)
    assert len(groups)==1 and len(groups[0])==4 and calls and len(closed)==3
    calls.clear();monkeypatch.setattr(refine,'candidate_mask',lambda *a:np.zeros((1,1),bool))
    groups=auto.cluster(ps,None)
    assert len(groups)==2 and not calls and len(closed)==6
    monkeypatch.setattr(refine,'candidate_mask',lambda *a:np.ones((1,1),bool))
    monkeypatch.setattr(RefineCache,'get',lambda *a:None)
    assert auto.cluster(ps,None) is None and len(closed)==9
