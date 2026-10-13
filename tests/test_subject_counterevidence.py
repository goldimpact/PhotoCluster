import numpy as np
import pytest

from photocluster import subject_auto as auto,complementary
from test_subject_auto import gv,cv,photos,prepare
from test_identity_refine import vec


def test_general_mask_preserves_an_alternate_frame_without_cross_frame_proof():
    a=gv(0);b=np.concatenate([gv(0),gv(.1)]);off=np.array([False]);offs=np.array([False,False])
    pa=vec();pb=np.concatenate([vec(),vec(.9)])
    match=auto.verify_pair(a,b,off,offs,None,None,.72,pa,pb,general_allowed=np.array([[False,True]]))
    assert match and match[1][1:]==(0,1)
    assert auto.verify_pair(a,b,off,offs,None,None,.72,pa,pb,general_allowed=np.zeros((1,2),bool)) is None
    with pytest.raises(ValueError):auto.verify_pair(a,b,off,offs,None,None,.72,general_allowed=np.ones((1,1),bool))
    match=complementary.verify(a,b,off,offs,None,None,pa,pb,pa,np.concatenate([vec(),vec(.98)]),.72,general_allowed=np.array([[False,True]]))
    assert match and match[1][1:]==(0,1)


def test_counterevidence_never_blocks_a_valid_identity_route():
    on=np.array([True]);x=gv(0);c=cv(0);p=vec();deny=np.zeros((1,1),bool)
    assert auto.verify_pair(x,x,on,on,c,c,.72,p,p,general_allowed=deny)[2]=='identity'
    assert complementary.verify(x,x,on,on,c,c,p,p,p,p,.72,general_allowed=deny)


def test_both_identity_models_must_contradict_under_strong_same_frame_domain(monkeypatch):
    prepare(monkeypatch,[gv(0),gv(.1)],[cv(0),cv(2.)],[np.array([False])]*2)
    for module in (auto.perceptual,auto.complementary,auto.identity_refine,auto.domain_refine):
        monkeypatch.setattr(module,'installed',lambda:True)
    monkeypatch.setattr(auto.local_context,'installed',lambda:False)
    closed=[];large_calls=[];domain=[.99];large=[-1.]
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):return vec()
        def close(self):closed.append(1)
    class Domain(Cache):
        def get(self,p):return np.array([[domain[0],1-domain[0]]],np.float32)
    class Large(Cache):
        def get(self,p):large_calls.append(p['key']);return vec() if p['key']=='0' else vec(large[0])
    monkeypatch.setattr(auto.perceptual,'VectorCache',Cache)
    monkeypatch.setattr(auto.complementary,'VectorCache',Cache)
    monkeypatch.setattr(auto.domain_refine,'VectorCache',Domain)
    monkeypatch.setattr(auto.identity_refine,'VectorCache',Large)
    assert auto.cluster(photos(2),None)==[] and large_calls and len(closed)==4
    domain[0]=.94;large_calls.clear()
    assert len(auto.cluster(photos(2),None)[0])==2 and not large_calls
    domain[0]=.99;large[0]=1.;large_calls.clear()
    assert len(auto.cluster(photos(2),None)[0])==2 and large_calls
    # A strong small identity score avoids loading the larger encoder at all.
    prepare(monkeypatch,[gv(0),gv(.1)],[cv(0),cv(.1)],[np.array([False])]*2)
    large_calls.clear();assert len(auto.cluster(photos(2),None)[0])==2 and not large_calls
    monkeypatch.setattr(Domain,'get',lambda *a:None)
    assert auto.cluster(photos(2),None) is None
