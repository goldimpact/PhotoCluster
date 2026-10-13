from types import SimpleNamespace
import io

import numpy as np
import pytest
from PIL import Image

from photocluster import domain_refine as domain, subject_auto as auto, subject


@pytest.fixture(autouse=True)
def without_optional_local_export(monkeypatch):
    monkeypatch.setattr(auto.local_context,'installed',lambda:False)


def test_probabilities_keep_upstream_scale_and_preprocessing(monkeypatch):
    seen=[]
    class Model:
        def get_inputs(self):return [SimpleNamespace(name='input')]
        def run(self,names,feed):
            seen.append(feed['input']);return [np.array([[.96,.04]],np.float32)]
    monkeypatch.setattr(domain,'session',lambda:Model())
    value=domain.encode([Image.new('RGB',(13,7),'red')])
    np.testing.assert_allclose(value,[[.96,.04]])
    assert seen[0].shape==(1,3,384,384)
    np.testing.assert_array_equal(seen[0][0,:,0,0],[1,-1,-1])
    assert domain.encode([],lambda:True).shape==(0,2)
    assert domain.encode([Image.new('RGB',(3,3))],lambda:True) is None


def test_real_domain_exclusion_is_frame_specific_and_never_enables_a_route():
    gates=np.array([True,True,True,False])
    scores=np.array([[.03,.97],[.5,.5],[.99,.01],[.99,.01]],np.float32)
    np.testing.assert_array_equal(domain.exclude_confident_real(gates,scores),[False,True,True,False])
    assert gates.tolist()==[True,True,True,False]
    with pytest.raises(ValueError):domain.exclude_confident_real(gates,scores[:1])


def test_photographed_objects_keep_general_route_when_style_says_3d(monkeypatch):
    from test_subject_auto import photos,gv,cv,prepare
    from test_identity_refine import vec
    prepare(monkeypatch,[gv(0),gv(.1)],[cv(0),cv(2.)],[np.array([True])]*2)
    for module in (auto.perceptual,auto.complementary,auto.identity_refine,domain):
        monkeypatch.setattr(module,'installed',lambda:True)
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):return vec()
        def close(self):pass
    class Domain(Cache):
        def get(self,p):return np.array([[.03,.97]],np.float32)
    for module in (auto.perceptual,auto.complementary,auto.identity_refine):monkeypatch.setattr(module,'VectorCache',Cache)
    monkeypatch.setattr(domain,'VectorCache',Domain)
    groups=auto.cluster(photos(2),None)
    assert len(groups)==1 and len(groups[0])==2
    assert groups[0][1]['relation']=='subject'
    monkeypatch.setattr(Domain,'get',lambda *a:None)
    assert auto.cluster(photos(2),None) is None


def test_same_frame_two_sided_domain_and_identity_support():
    from test_identity_refine import vec
    off=np.array([False]);on=np.array([True]);a=vec()
    mask=domain.candidate_mask(off,on,a,a,a,a,.72)
    assert mask.any()
    assert not domain.candidate_mask(on,on,a,a,a,a,.72).any()
    assert not domain.routed_mask(mask,np.array([[.99,.01]]),np.array([[.5,.5]])).any()
    mask=domain.routed_mask(mask,np.array([[.99,.01]]),np.array([[.91,.09]]))
    assert not domain.identity_mask(mask,a,vec(.7),.72).any()
    assert domain.identity_mask(mask,a,vec(.8),.72).any()
    # Strong evidence on different frames cannot be combined.
    mask=domain.candidate_mask(off,np.array([False,False]),a,np.concatenate([vec(.4),a]),a,
                               np.concatenate([a,vec(.8)]),.72)
    assert not mask.any()
    with pytest.raises(ValueError):domain.routed_mask(mask,np.zeros((1,2)),np.zeros((1,2)))


def test_domain_cache_is_separate_and_changes_result_identity(tmp_path,monkeypatch):
    version=['one'];calls=[]
    monkeypatch.setattr(domain,'model_identity',lambda:version[0])
    monkeypatch.setattr(domain,'encode',lambda *a:(calls.append(1) or np.array([[.95,.05]],np.float32)))
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(4,4))])
    p=dict(key='a',sha256='sha')
    with __import__('contextlib').closing(domain.VectorCache(tmp_path)) as cache:
        cache.get(p);cache.get(p)
    first=auto.model_identity();version[0]='two';assert first!=auto.model_identity()
    with __import__('contextlib').closing(domain.VectorCache(tmp_path)) as cache:cache.get(p)
    assert len(calls)==2 and (tmp_path/'subject-domain-refine.sqlite3').is_file()


def test_lazy_domain_route_recovers_missed_identity_and_abstains(monkeypatch):
    from test_subject_auto import photos,gv,cv,prepare
    from test_identity_refine import vec
    ps=photos(4)
    prepare(monkeypatch,[gv(0),gv(2),gv(.1),gv(2.1)],
            [cv(0)]*4,[np.array([False])]*4)
    for module in (auto.perceptual,auto.complementary,auto.identity_refine,domain):
        monkeypatch.setattr(module,'installed',lambda:True)
    called=[];closed=[];confidence=[.99];semantic=[1.]
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):return vec()
        def close(self):closed.append(1)
    class Semantic(Cache):
        def get(self,p):return vec() if int(p['key'])%2==0 else vec(semantic[0])
    class Domain(Cache):
        def get(self,p):
            called.append(p['key']);x=confidence[0] if int(p['key'])%2 else .99
            return np.array([[x,1-x]],np.float32)
    monkeypatch.setattr(auto.perceptual,'VectorCache',Cache)
    monkeypatch.setattr(auto.complementary,'VectorCache',Semantic)
    monkeypatch.setattr(auto.identity_refine,'VectorCache',Cache)
    monkeypatch.setattr(domain,'VectorCache',Domain)
    monkeypatch.setattr(auto.complementary,'verify',lambda *a:None)
    groups=auto.cluster(ps,None)
    assert len(groups)==1 and len(groups[0])==4 and called and len(closed)==4
    called.clear();confidence[0]=.4
    assert len(auto.cluster(ps,None))==2 and called
    called.clear();semantic[0]=.8
    assert len(auto.cluster(ps,None))==2 and sorted(called)==['0','1','2','3']
    # Only the two already-matching general pairs are checked for counterevidence;
    # the failed semantic cross-group candidate does not request a new domain check.
    semantic[0]=1.;monkeypatch.setattr(Domain,'get',lambda *a:None)
    assert auto.cluster(ps,None) is None


def test_installer_rejects_bad_weights(tmp_path,monkeypatch):
    from scripts import setup_domain_refine as setup
    model=tmp_path/'model.onnx';model.write_bytes(b'old');monkeypatch.setattr(setup,'MODEL',model)
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:io.BytesIO(b'bad')))
    with pytest.raises(RuntimeError,match='checksum'):setup.install()
    assert model.read_bytes()==b'old' and not model.with_suffix('.download').exists()
