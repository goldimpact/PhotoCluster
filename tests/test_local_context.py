from contextlib import closing
from types import SimpleNamespace
import io

import numpy as np
import pytest
from PIL import Image

from photocluster import local_context as local, subject, subject_merge, subject_auto as auto


@pytest.fixture(autouse=True)
def without_extra_identity_export(monkeypatch):
    monkeypatch.setattr(auto.identity_extra,'installed',lambda:False)


def vec(cosine=1):
    v=np.zeros((1,768),np.float32);v[0,:2]=cosine,np.sqrt(max(0,1-cosine*cosine));return v


def test_detector_preprocessing_single_view_and_multisubject_abstention(monkeypatch):
    rows=[(80,80,40,40,.9),(80,80,40,40,.8)];seen=[]
    class Model:
        def run(self,names,feed):
            seen.append(feed['images']);return [np.array(rows,np.float32).T[None]]
    monkeypatch.setattr(local,'session',lambda:Model())
    view,box=local.context(Image.new('RGB',(160,160),'red'))
    assert seen[0].shape==(1,3,160,160) and box==(32,27,128,123)
    np.testing.assert_array_equal(seen[0][0,:,0,0],[1,0,0])
    assert view.size==(96,96)
    rows.append((130,130,20,20,.9));assert local.context(Image.new('RGB',(160,160))) is None
    rows[:]=[(80,80,40,40,.1)];assert local.context(Image.new('RGB',(160,160))) is None
    with pytest.raises(subject_merge.Cancelled):local.context(Image.new('RGB',(160,160)),lambda:True)


def test_cache_negative_hits_budget_force_and_sampling_identity(tmp_path,monkeypatch):
    calls=[];found=[False]
    monkeypatch.setattr(local,'model_identity',lambda:'models1')
    monkeypatch.setattr(local,'MAX_NEW_MEDIA',1)
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(64,64))])
    def context(im,*args):
        calls.append(1);return (im,(0,0,64,64)) if found[0] else None
    monkeypatch.setattr(local,'context',context)
    for module in (local.character,local.perceptual,local.complementary,local.identity_refine):
        monkeypatch.setattr(module,'encode',lambda *a:vec())
    p=dict(key='one',sha256='sha');q=dict(key='two',sha256='sha2')
    with closing(local.VectorCache(tmp_path)) as cache:
        assert cache.get(p) is None and cache.get(p) is None
        assert cache.get(q) is None and len(calls)==1
        assert cache.con.execute('SELECT COUNT(*) FROM contexts').fetchone()[0]==1
    found[0]=True
    with closing(local.VectorCache(tmp_path)) as cache:
        assert cache.get(p) is None
        assert cache.get(q)['box']==(0,0,64,64)
    with closing(local.VectorCache(tmp_path,force=True)) as cache:
        assert cache.get(p)['frame']==0
        cache.memory.clear()
        assert cache.get(p)['frame']==0 and len(calls)==3
    monkeypatch.setattr(local,'model_identity',lambda:'models2')
    with closing(local.VectorCache(tmp_path)) as cache:assert cache.get(p)['frame']==0
    assert len(calls)==4
    with closing(local.VectorCache(tmp_path,lambda:True)) as cache:
        with pytest.raises(subject_merge.Cancelled):cache.get(p)


def test_original_frame_alignment_domain_conflicts_and_crop_provenance():
    x=vec();whole=dict(small=np.concatenate([x,x]),large=np.concatenate([x,x]),
        semantic=np.concatenate([x,x]),perception=np.concatenate([x,x]))
    a=dict(frame=1,box=(2,3,45,49),small=x,large=x,semantic=x,perception=x)
    b=dict(a,frame=0,box=(0,1,40,60))
    mask=np.zeros((2,2),bool);mask[1,0]=True
    result=local.verify(mask,a,b,whole,whole,.72)
    assert result[1][1:]==(1,0) and result[2]['reference_box']==a['box']
    assert result[2]['match_box']==b['box']
    assert local.verify(np.zeros((2,2),bool),a,b,whole,whole,.72) is None
    result=local.verify(mask,a,None,whole,whole,.72)
    assert result[2]['match_box'] is None and result[1][1:]==(1,0)
    bad=dict(b,small=vec(-1));badwhole=dict(whole,small=np.concatenate([vec(-1),vec(-1)]))
    assert local.verify(mask,a,bad,whole,badwhole,.72) is None
    domain=np.array([[.99,.01],[.1,.9]])
    gate=local.whole_mask(domain,domain,whole['small'],whole['small'],whole['semantic'],whole['semantic'])
    np.testing.assert_array_equal(gate,[[True,False],[False,False]])


def test_retrieval_includes_nonreference_members_scope_budget_and_cancel(monkeypatch):
    photos=[dict(album='a') for _ in range(5)];groups=[[0,1,2],[3,4]]
    chars={i:vec(-1 if i<2 else 1) for i in range(5)};gates=[np.array([True])]*5
    proposals=local.proposals(groups,photos,chars,gates,'all',lambda:False)
    assert any(a==0 and b==1 and witness==2 for a,b,witness,_ in proposals)
    photos[3]['album']='b';photos[4]['album']='b'
    assert not local.proposals(groups,photos,chars,gates,'album',lambda:False)
    monkeypatch.setattr(local,'MAX_RETRIEVAL_FRAMES',2)
    assert not local.proposals(groups,photos,chars,gates,'all',lambda:False)
    with pytest.raises(subject_merge.Cancelled):local.proposals(groups,photos,chars,gates,'all',lambda:True)


def test_cancellation_during_encoding_does_not_write_partial_cache(tmp_path,monkeypatch):
    cancelled=[False]
    monkeypatch.setattr(local,'model_identity',lambda:'test')
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(64,64))])
    monkeypatch.setattr(local,'context',lambda im,*args:(im,(0,0,64,64)))
    def first(*a):cancelled[0]=True;return vec()
    monkeypatch.setattr(local.character,'encode',first)
    with closing(local.VectorCache(tmp_path,lambda:cancelled[0])) as cache:
        with pytest.raises(subject_merge.Cancelled):cache.get(dict(key='one',sha256='sha'))
        assert cache.con.execute('SELECT COUNT(*) FROM contexts').fetchone()[0]==0


def test_uninstalled_local_model_does_not_change_other_optional_routes(monkeypatch):
    from test_subject_auto import prepare,photos,gv,cv
    prepare(monkeypatch,[gv(0),gv(.1)],[cv(0),cv(.1)],[np.array([True])]*2)
    monkeypatch.setattr(auto.perceptual,'installed',lambda:False)
    monkeypatch.setattr(auto.complementary,'installed',lambda:False)
    monkeypatch.setattr(local,'VectorCache',lambda *a:pytest.fail('No optional dependencies'))
    assert len(auto.cluster(photos(2),None)[0])==2


def test_installer_preserves_previous_model_on_checksum_failure(tmp_path,monkeypatch):
    from scripts import setup_local_context as setup
    model=tmp_path/'model.onnx';model.write_bytes(b'old');monkeypatch.setattr(setup,'MODEL',model)
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:io.BytesIO(b'bad')))
    with pytest.raises(RuntimeError,match='checksum'):setup.install()
    assert model.read_bytes()==b'old' and not model.with_suffix('.download').exists()


def test_pipeline_local_refinement_publishes_evidence_and_closes_on_cancel(monkeypatch):
    from test_subject_auto import prepare,photos,gv,cv
    ps=photos(4)
    prepare(monkeypatch,[gv(0),gv(2),gv(.1),gv(2.1)],[cv(0)]*4,[np.array([False])]*4)
    for module in (auto.perceptual,auto.complementary,auto.identity_refine,auto.domain_refine,local):
        monkeypatch.setattr(module,'installed',lambda:True)
    closed=[];calls=[];stopped=[False]
    class Cache:
        def __init__(self,*args):pass
        def get(self,p):return vec()
        def close(self):closed.append(1)
    class Domain(Cache):
        def get(self,p):return np.array([[.99,.01]],np.float32)
    class Local(Cache):
        def get(self,p):
            calls.append(p['key'])
            if stopped[0]:raise subject_merge.Cancelled()
            return dict(frame=0,box=(0,0,64,64),small=vec(),large=vec(),semantic=vec(),perception=vec())
    for module in (auto.perceptual,auto.complementary,auto.identity_refine):monkeypatch.setattr(module,'VectorCache',Cache)
    monkeypatch.setattr(auto.domain_refine,'VectorCache',Domain)
    monkeypatch.setattr(local,'VectorCache',Local)
    monkeypatch.setattr(auto.complementary,'verify',lambda *args:None)
    monkeypatch.setattr(auto.domain_refine,'candidate_mask',lambda *args:np.zeros((1,1),bool))
    groups=auto.cluster(ps,None)
    assert len(groups)==1 and len(groups[0])==4 and calls and len(closed)==5
    assert any(p.get('subject_evidence',{}).get('kind')=='local_context' for p in groups[0])
    stopped[0]=True
    assert auto.cluster(ps,None) is None and len(closed)==10


def test_large_encoder_only_runs_after_cheap_evidence_and_reuses_partial_cache(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(local,'model_identity',lambda:'compatible-v11')
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(64,64))])
    monkeypatch.setattr(local,'context',lambda image,*args:(image,(0,0,64,64)))
    for module in (local.character,local.perceptual,local.complementary):
        monkeypatch.setattr(module,'encode',lambda *a:vec())
    monkeypatch.setattr(local.identity_refine,'encode',lambda *a:(calls.append(1) or vec()))
    p=dict(key='one',sha256='sha')
    whole=dict(small=vec(-1),large=vec(),semantic=vec(),perception=vec())
    with closing(local.VectorCache(tmp_path)) as cache:
        a=cache.get(p);assert 'large' not in a and not calls
        assert local.verify(np.ones((1,1),bool),a,None,whole,whole,.72,lambda:cache.large(p)) is None
        assert not calls
    # Reopen a partial record without re-detection or repeat cheap encoding.
    monkeypatch.setattr(local,'context',lambda *a:pytest.fail('Reuse recorded crop'))
    whole['small']=vec()
    with closing(local.VectorCache(tmp_path)) as cache:
        a=cache.get(p)
        assert local.verify(np.ones((1,1),bool),a,None,whole,whole,.72,lambda:cache.large(p))
        cache.memory.clear();assert cache.large(p) is not None and len(calls)==1
    with closing(local.VectorCache(tmp_path)) as cache:assert 'large' in cache.get(p)
    assert len(calls)==1


def test_large_budget_and_cancellation_preserve_resumable_cheap_features(tmp_path,monkeypatch):
    stop=[False];calls=[]
    monkeypatch.setattr(local,'model_identity',lambda:'test')
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(64,64))])
    monkeypatch.setattr(local,'context',lambda image,*args:(image,(0,0,64,64)))
    for module in (local.character,local.perceptual,local.complementary):
        monkeypatch.setattr(module,'encode',lambda *a:vec())
    def encode(*a):calls.append(1);return None if stop[0] else vec()
    monkeypatch.setattr(local.identity_refine,'encode',encode)
    p=dict(key='one',sha256='sha')
    with closing(local.VectorCache(tmp_path)) as cache:assert 'large' not in cache.get(p)
    monkeypatch.setattr(local,'MAX_NEW_MEDIA',0)
    with closing(local.VectorCache(tmp_path)) as cache:
        assert cache.large(p) is None and not calls
        assert 'small' in cache.get(p) and 'large' not in cache.get(p)
    monkeypatch.setattr(local,'MAX_NEW_MEDIA',1);stop[0]=True
    with closing(local.VectorCache(tmp_path)) as cache:
        with pytest.raises(subject_merge.Cancelled):cache.large(p)
    stop[0]=False
    with closing(local.VectorCache(tmp_path)) as cache:
        assert 'large' not in cache.get(p)
        assert cache.large(p) is not None
    assert len(calls)==2
