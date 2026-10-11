import numpy as np
import pytest
from PIL import Image

from photocluster import perceptual, subject, subject_auto as auto


def general():
    result=np.zeros((1,6,384),np.float32);result[:,:,0]=1
    return result


def vector(cosine,dim=768):
    result=np.zeros((1,dim),np.float32)
    result[0,:2]=[cosine,np.sqrt(max(0,1-cosine*cosine))]
    return result


def test_perceptual_disagreement_rejects_style_but_does_not_gate_on_dino():
    g=general();off=np.array([False]);on=np.array([True]);a=vector(1)
    assert auto.verify_pair(g,g,off,off,None,None,.72)
    assert auto.verify_pair(g,g,off,off,None,None,.72,a,vector(.4)) is None
    assert auto.verify_pair(g,g,off,off,None,None,.72,a,vector(.7))
    # Same identity can survive DINO disagreement if perceptual evidence supports it.
    assert auto.verify_pair(g,-g,on,on,a,vector(.8),.72,a,vector(.7))


def test_support_cannot_leak_between_animation_frames():
    g=general();on=np.array([True]);a=vector(1)
    gb=np.concatenate([g,g]);cb=np.concatenate([vector(.8),vector(-1)])
    pb=np.concatenate([vector(.4),vector(.9)])
    assert auto.verify_pair(g,gb,on,np.array([True,True]),a,cb,.72)
    assert auto.verify_pair(g,gb,on,np.array([True,True]),a,cb,.72,a,pb) is None
    cb[1]=a[0]
    match=auto.verify_pair(g,gb,on,np.array([True,True]),a,cb,.72,a,pb)
    assert match[1][1:]==(0,1)


def test_missing_or_misaligned_support_is_not_silently_ignored():
    g=general();off=np.array([False]);a=vector(1)
    with pytest.raises(ValueError,match='Missing'):
        auto.verify_pair(g,g,off,off,None,None,.72,a,None)
    with pytest.raises(ValueError,match='Incompatible'):
        auto.verify_pair(g,g,off,off,None,None,.72,a,np.concatenate([a,a]))


def test_bounded_cache_flushes_on_close_versions_sha_and_cancels(tmp_path,monkeypatch):
    calls=[];version=['v1'];cancel=[False]
    monkeypatch.setattr(perceptual,'model_identity',lambda:version[0])
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(8,8))])
    monkeypatch.setattr(perceptual,'encode',lambda *a:(calls.append(True) or vector(1)))
    p=dict(key='k',sha256='one')
    cache=perceptual.VectorCache(tmp_path,lambda:cancel[0])
    cache.get(p);cache.get(p);assert len(calls)==1
    for i in range(70):cache.get(dict(key=str(i),sha256=str(i)))
    assert len(cache.memory)==64
    cache.close()
    cache=perceptual.VectorCache(tmp_path,lambda:cancel[0]);cache.get(p)
    assert len(calls)==71
    cache.get(dict(p,sha256='two'));assert len(calls)==72
    cancel[0]=True;assert cache.get(p) is None
    cache.close();cancel[0]=False;version[0]='v2'
    cache=perceptual.VectorCache(tmp_path);cache.get(p);cache.close()
    assert len(calls)==73


def test_optional_model_is_part_of_final_result_identity(monkeypatch):
    monkeypatch.setattr(perceptual,'model_identity',lambda:'perceptual-A')
    first=auto.model_identity()
    monkeypatch.setattr(perceptual,'model_identity',lambda:'perceptual-B')
    assert first!=auto.model_identity()


def test_cluster_only_encodes_candidates_and_always_closes(monkeypatch):
    photos=[dict(key=str(i),sha256=str(i),album='/test',size=10-i,width=100,height=100,sharpness=10-i) for i in range(3)]
    g=general();calls=[];closed=[]
    monkeypatch.setattr(subject,'vectors',lambda *a:[g,g,-g])
    monkeypatch.setattr(auto,'load_routes',lambda *a:[np.array([False])]*3)
    monkeypatch.setattr(perceptual,'installed',lambda:True)
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):calls.append(p['key']);return vector(1)
        def close(self):closed.append(True)
    monkeypatch.setattr(perceptual,'VectorCache',Cache)
    groups=auto.cluster(photos,None)
    assert [[p['key'] for p in g] for g in groups]==[['0','1']]
    assert calls==['0','1'] and closed==[True]
    monkeypatch.setattr(Cache,'get',lambda *a:None)
    assert auto.cluster(photos,None) is None
    assert closed==[True,True]


def test_export_rejects_unknown_weights_before_importing_optional_dependencies(tmp_path):
    from scripts.export_subject_perceptual import export,FILES
    for name in FILES:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='hash'):
        export(tmp_path,tmp_path,tmp_path/'output.onnx')
    assert not (tmp_path/'output.onnx').exists()
