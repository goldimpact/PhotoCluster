from types import SimpleNamespace
import io

import numpy as np
import pytest
from PIL import Image

from photocluster import complementary as module, subject_merge, subject, subject_auto as auto


@pytest.fixture(autouse=True)
def no_optional_larger_model(monkeypatch):
    monkeypatch.setattr(auto.identity_refine,'installed',lambda:False)


def unit(cosine=1):
    v=np.zeros((1,768),np.float32);v[0,:2]=cosine,np.sqrt(max(0,1-cosine*cosine))
    return v


def general():
    v=np.zeros((1,6,384),np.float32);v[:,:,0]=1
    return v


def test_general_route_requires_regions_and_same_frame_evidence():
    g=general();off=np.array([False]);a=unit()
    assert module.verify(g,g,off,off,None,None,a,unit(.6),a,unit(.95),.72)
    assert module.verify(g,-g,off,off,None,None,a,unit(.9),a,unit(.99),.72) is None
    assert module.verify(g,g,off,np.array([True]),None,None,a,a,a,a,.72) is None
    # Strong perception and semantics on different animation frames cannot combine.
    assert module.verify(g,np.concatenate([g,g]),off,np.array([False,False]),None,None,
        a,np.concatenate([unit(.4),unit(.9)]),a,np.concatenate([unit(.99),unit(.8)]),.72) is None


def test_identity_route_needs_all_three_signals_without_dino_veto():
    g=general();on=np.array([True]);a=unit()
    assert module.verify(g,-g,on,on,a,unit(.66),a,unit(.6),a,unit(.95),.72)
    assert module.verify(g,g,on,on,a,unit(.5),a,a,a,a,.72) is None
    assert module.verify(g,g,on,on,a,a,a,unit(.4),a,a,.72) is None
    assert module.verify(g,g,on,on,a,a,a,a,a,unit(.8),.72) is None
    assert module.verify(g,-g,on,on,a,unit(.66),a,unit(.65),a,unit(.89),.72)
    assert module.verify(g,g,on,on,a,unit(.66),a,unit(.55),a,unit(.89),.72) is None
    assert module.verify(g,g,on,on,a,unit(.66),a,unit(.65),a,unit(.87),.72) is None
    # Do not borrow the strong appearance from a different sampled frame.
    assert module.verify(g,np.concatenate([g,g]),on,np.array([True,True]),
        a,np.concatenate([unit(.66),unit(.5)]),a,np.concatenate([unit(.55),unit(.9)]),
        a,np.concatenate([unit(.89),unit(.99)]),.72) is None
    with pytest.raises(ValueError,match='Incompatible'):
        module.verify(g,g,on,on,a,a,a,a,np.concatenate([a,a]),a,.72)


def test_exact_preprocess_pool_output_and_cancellation(monkeypatch):
    inputs=[]
    class Model:
        def get_inputs(self):return [SimpleNamespace(name='pixels')]
        def run(self,names,feed):
            assert names==['pooler_output'];inputs.append(feed['pixels'])
            return [np.repeat(unit(),len(feed['pixels']),axis=0)]
    monkeypatch.setattr(module,'session',lambda:Model())
    image=Image.fromarray(np.random.default_rng(2).integers(0,256,(19,23,3),dtype=np.uint8))
    result=module.encode([image]*5)
    expected=(np.asarray(image.resize((224,224),Image.Resampling.BILINEAR),np.float32)/255-.5).transpose(2,0,1)/.5
    np.testing.assert_array_equal(inputs[0][0],expected)
    assert result.shape==(5,768) and [len(x) for x in inputs]==[4,1]
    assert module.encode([image],lambda:True) is None


def test_separate_cache_versions_sampling_and_cancellation(tmp_path,monkeypatch):
    calls=[];version=['one'];stop=[False]
    monkeypatch.setattr(module,'model_identity',lambda:version[0])
    monkeypatch.setattr(module,'encode',lambda *a:(calls.append(1) or unit()))
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(2,2))])
    p=dict(key='p',sha256='sha')
    for _ in range(2):
        cache=module.VectorCache(tmp_path,lambda:stop[0]);cache.get(p);cache.close()
    assert len(calls)==1 and (tmp_path/'subject-complementary.sqlite3').is_file()
    assert not (tmp_path/'subject-perceptual.sqlite3').exists()
    version[0]='two';cache=module.VectorCache(tmp_path,lambda:stop[0]);cache.get(p)
    cache.get(dict(p,animated=True));assert len(calls)==3
    stop[0]=True;assert cache.get(p) is None;cache.close()


def test_candidate_limits_album_scope_and_cancel():
    photos=[dict(key=str(i),album=str(i//8)) for i in range(48)]
    groups=[list(range(i,i+4)) for i in range(0,48,4)]
    class Cache:
        def get(self,p):return unit()
    proposed=module.proposals(groups,photos,Cache(),'album',lambda:False,None)
    assert len(proposed)<=len(photos)*4
    for a,b,witness,score in proposed:
        assert photos[groups[a][0]]['album']==photos[groups[b][0]]['album']
        assert witness in groups[a] and score>=.88
    with pytest.raises(subject_merge.Cancelled):
        module.proposals(groups,photos,Cache(),'all',lambda:True,None)


def test_all_contributing_models_invalidate_result_identity(monkeypatch):
    version=['a'];monkeypatch.setattr(module,'model_identity',lambda:version[0])
    first=auto.model_identity();version[0]='b';assert first!=auto.model_identity()


def test_download_rejects_wrong_sha_without_loading_model(tmp_path,monkeypatch):
    from scripts import setup_complementary as setup
    target=tmp_path/'model.onnx';target.write_bytes(b'previous')
    monkeypatch.setattr(setup,'MODEL',target)
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:io.BytesIO(b'bad')))
    with pytest.raises(RuntimeError,match='checksum'):setup.install()
    assert target.read_bytes()==b'previous' and not target.with_suffix('.download').exists()


def test_postpass_finds_groups_without_first_pass_edges_and_closes_caches(monkeypatch):
    from test_subject_auto import photos,gv,cv,prepare
    ps=photos(4);gs=[gv(0),gv(2),gv(.1),gv(2.1)]
    prepare(monkeypatch,gs,[cv(0)]*4,[np.array([False])]*4)
    monkeypatch.setattr(module,'installed',lambda:True)
    monkeypatch.setattr(auto.perceptual,'installed',lambda:True)
    closed=[];phases=[]
    class Cache:
        def __init__(self,*a):pass
        def get(self,p):return unit()
        def close(self):closed.append(1)
    monkeypatch.setattr(module,'VectorCache',Cache);monkeypatch.setattr(auto.perceptual,'VectorCache',Cache)
    monkeypatch.setattr(module,'verify',lambda *a:(.95,(.95,0,0),'complementary'))
    groups=auto.cluster(ps,None,progress=lambda d,t,p:phases.append(p))
    assert len(groups)==1 and {p['key'] for p in groups[0]}=={'0','1','2','3'}
    assert 'subject_complement' in phases and len(closed)==2
    assert all(p['reference_frame']==0 for p in groups[0][1:])
    stopped=[False]
    def progress(done,total,phase):
        if phase=='subject_complement':stopped[0]=True
    assert auto.cluster(ps,None,progress=progress,cancelled=lambda:stopped[0]) is None
    assert len(closed)==4


def test_retrieval_memory_budget_remains_bounded(monkeypatch):
    monkeypatch.setattr(module,'MAX_RETRIEVAL_FRAMES',3)
    photos=[dict(key=str(i),album='a') for i in range(10)]
    calls=[]
    class Cache:
        def get(self,p):calls.append(p['key']);return unit()
    result=module.proposals([[i,i+1] for i in range(0,10,2)],photos,Cache(),'all',lambda:False,None)
    assert len(calls)==4 and len(result)<=3*4


def test_api_reports_optional_review_and_invalidates_old_result(tmp_path,monkeypatch):
    from photocluster import app as api
    from photocluster.service import Service
    from fastapi.testclient import TestClient
    service=Service(tmp_path);monkeypatch.setattr(api,'service',service)
    monkeypatch.setattr(auto.perceptual,'installed',lambda:True)
    present=[True];monkeypatch.setattr(module,'installed',lambda:present[0])
    service.result={'groups':[],'ungrouped':[],'summary':dict(mode='subject',subject_engine='auto',
        subject_policy=auto.VERSION,subject_perceptual=True,subject_complementary=True)}
    with TestClient(api.app) as client:
        assert client.get('/api/subject-model').json()['complementary'] is True
        assert client.get('/api/groups').json()['summary']['recognition_outdated'] is False
        present[0]=False
        assert client.get('/api/groups').json()['summary']['recognition_outdated'] is True
    assert 'recognition_outdated' not in service.result['summary']
