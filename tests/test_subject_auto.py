import hashlib
import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from photocluster import subject, character, subject_auto as auto


@pytest.fixture(autouse=True)
def base_pipeline_without_optional_export(monkeypatch):
    monkeypatch.setattr(auto.perceptual,'installed',lambda:False)
    monkeypatch.setattr(auto.complementary,'installed',lambda:False)
    monkeypatch.setattr(auto.identity_refine,'installed',lambda:False)
    monkeypatch.setattr(auto.domain_refine,'installed',lambda:False)
    monkeypatch.setattr(auto.local_context,'installed',lambda:False)
    monkeypatch.setattr(auto.identity_extra,'installed',lambda:False)


def gv(angle):
    v=np.zeros((1,6,384),np.float32);v[:,:,0]=np.cos(angle);v[:,:,1]=np.sin(angle)
    return v


def cv(angle):
    v=np.zeros((1,768),np.float32);v[:,0]=np.cos(angle);v[:,1]=np.sin(angle)
    return v


def photos(n):
    return [dict(key=str(i),sha256=str(i),album='/test',size=100-i,width=100,height=100,sharpness=100-i) for i in range(n)]


def prepare(monkeypatch,gs,cs,masks):
    monkeypatch.setattr(subject,'vectors',lambda *a:gs)
    monkeypatch.setattr(auto,'load_routes',lambda *a:masks)
    requested=[]
    def vectors(items,*args):
        requested.extend(p['key'] for p in items)
        return [cs[int(p['key'])] for p in items]
    monkeypatch.setattr(character,'vectors',vectors)
    return requested


def test_equal_quality_reference_and_grouping_do_not_depend_on_inventory_order(monkeypatch):
    from itertools import permutations
    ps=[dict(p,size=100,sharpness=10) for p in photos(3)]
    # The middle vector can match both ends; starting from an end splits them.
    gs={'0':gv(0),'1':gv(.65),'2':gv(1.3)}
    monkeypatch.setattr(subject,'vectors',lambda items,*a:[gs[p['key']] for p in items])
    monkeypatch.setattr(auto,'load_routes',lambda items,*a:[np.array([False]) for p in items])
    baseline=auto.cluster(ps,None)
    assert baseline and baseline[0][0]['key']=='2'
    for order in permutations(ps):assert auto.cluster(list(order),None)==baseline
    # Real quality differences still precede the content/key tie breaker.
    preferred=[dict(p,width=200 if p['key']=='0' else 100) for p in ps]
    assert auto.cluster(preferred,None)[0][0]['key']=='0'


def test_one_scan_groups_general_and_specialist_matches_without_partitioning(monkeypatch):
    gs=[gv(x) for x in (0,.2,1.8,3)]
    cs=[cv(x) for x in (0,0,0,.2)]
    requested=prepare(monkeypatch,gs,cs,[np.array([False]),np.array([False]),np.array([True]),np.array([True])])
    groups=auto.cluster(photos(4),None)
    assert [{p['key'] for p in g} for g in groups]==[{'0','1'},{'2','3'}]
    assert requested==['2','3']
    assert all(p['relation']=='subject' for g in groups for p in g[1:])


def test_specialist_cannot_match_an_ineligible_frame_or_create_chains(monkeypatch):
    gs=[gv(x) for x in (0,1.5,3)]
    cs=[cv(0),cv(.7),cv(1.4)]
    prepare(monkeypatch,gs,cs,[np.array([True])]*3)
    groups=auto.cluster(photos(3),None)
    assert [[p['key'] for p in g] for g in groups]==[['0','1']]
    # Same specialist vectors but one frame is outside its route: no forced merge.
    prepare(monkeypatch,gs[:2],[cv(0),cv(0)],[np.array([True]),np.array([False])])
    assert auto.cluster(photos(2),None)==[]


def test_applicable_identity_disagreement_blocks_shared_style_merge(monkeypatch):
    prepare(monkeypatch,[gv(0),gv(.1)],[cv(0),cv(2)],[np.array([True])]*2)
    assert auto.cluster(photos(2),None)==[]


def distinctive_regions():
    v=np.zeros((1,6,384),np.float32)
    v[0,0,0]=v[0,1,1]=1
    for i in range(4):v[0,i+2,i+2]=1
    return v


def test_one_common_region_and_whole_average_are_not_identity_support():
    a=distinctive_regions();b=a.copy()
    for i in (3,4,5):
        b[0,i]=0;b[0,i,i+10]=1
    assert subject.similarity(a,b)[0]>.99  # Old verifier falsely accepts.
    assert auto.general_scores(a,b,.72)[0,0]<0
    # A global patch average also cannot supply three local correspondences.
    b[0,2]=0;b[0,2,20]=1
    assert subject.similarity(a,b)[0]>.99
    assert auto.general_scores(a,b,.72)[0,0]<0


def test_many_regions_cannot_all_reuse_one_target_region():
    a=distinctive_regions();b=a.copy()
    a[0,2:]=a[0,2]
    assert subject.similarity(a,b)[0]>.99
    assert auto.general_scores(a,b,.72)[0,0]<0


def test_three_distinct_matches_allow_reordering_and_one_occlusion():
    a=distinctive_regions();b=a.copy();b[0,2:]=a[0,[4,2,5,3]]
    b[0,5]=0;b[0,5,20]=1
    assert auto.general_scores(a,b,.72)[0,0]==pytest.approx(.85)
    match=auto.verify_pair(a,b,np.array([False]),np.array([False]),None,None,.72)
    assert match and match[2]=='regions'


def test_inconsistent_route_does_not_fall_back_to_style(monkeypatch):
    prepare(monkeypatch,[gv(0),gv(0)],[cv(0),cv(0)],[np.array([True]),np.array([False])])
    assert auto.cluster(photos(2),None)==[]


def test_all_frame_pairs_checked_after_rejecting_best_style_frame():
    a=gv(0);b=np.concatenate([gv(0),gv(.2)])
    match=auto.verify_pair(a,b,np.array([False]),np.array([True,False]),None,None,.72)
    assert match and match[1][1:]==(0,1)


def test_retrieval_remains_a_superset_of_conservative_region_verification():
    rng=np.random.default_rng(12)
    for _ in range(40):
        a=subject.unit(rng.normal(size=(2,6,384)).astype(np.float32))
        b=subject.unit(a+rng.normal(scale=.02,size=a.shape).astype(np.float32))
        old=subject.similarity(a,b)[0]
        for threshold in (.65,.72,.80):
            assert auto.general_scores(a,b,threshold).max()<=old+1e-6


def test_frame_gate_is_pair_specific_and_reports_original_frame_positions(monkeypatch):
    gs=[np.concatenate([gv(0),gv(0)]),np.concatenate([gv(2),gv(2)])]
    cs=[np.concatenate([cv(0),cv(2)]),np.concatenate([cv(.1),cv(-2)])]
    masks=[np.array([False,True])]*2
    prepare(monkeypatch,gs,cs,masks)
    assert auto.cluster(photos(2),None)==[]  # Ineligible frame 0 does not leak through.
    cs[1][1]=cs[0][1]
    groups=auto.cluster(photos(2),None)
    assert groups[0][1]['reference_frame']==1 and groups[0][1]['match_frame']==1


def test_scope_cancel_and_reference_exactness(monkeypatch):
    prepare(monkeypatch,[gv(0),gv(.2),gv(.2)],[cv(0)]*3,[np.array([False])]*3)
    p=photos(3);p[1]['album']='/other';p[2]['sha256']=p[1]['sha256']
    assert {x['key'] for x in auto.cluster(p,None,scope='album')[0]}=={'0','2'}
    assert auto.cluster(p,None,cancelled=lambda:True) is None
    group=auto.cluster(p,None)[0]
    assert group[1]['score']==group[2]['score']<1


def test_routing_cache_and_all_model_versions(tmp_path,monkeypatch):
    version=['v1'];calls=[]
    monkeypatch.setattr(auto,'routing_identity',lambda:version[0])
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(20,20))])
    monkeypatch.setattr(auto,'routing_scores',lambda *a:(calls.append(True) or np.array([[.1,.5,0,.4,0]],np.float32)))
    for force in (False,False,True):auto.load_routes(photos(1),tmp_path,None,lambda:False,force)
    assert len(calls)==2
    version[0]='v2';auto.load_routes(photos(1),tmp_path,None,lambda:False,False);assert len(calls)==3
    monkeypatch.setattr(subject,'model_identity',lambda:'general')
    monkeypatch.setattr(character,'model_identity',lambda:'character')
    assert 'general' in auto.model_identity() and 'character' in auto.model_identity() and 'v2' in auto.model_identity()


def test_unified_api_defaults_and_model_bundle(tmp_path,monkeypatch):
    from photocluster.app import Scan,SubjectModelInstall
    assert Scan(albums=[],mode='subject').subject_engine=='auto'
    assert SubjectModelInstall().engine=='auto'
    for module,name in ((auto,'route'),(subject,'general'),(character,'character')):
        monkeypatch.setattr(module,'MODEL',tmp_path/name)
    assert not auto.installed()
    auto.MODEL.touch();subject.MODEL.touch();assert not auto.installed()
    character.MODEL.touch();assert auto.installed()


def test_combined_results_invalidate_when_router_or_policy_changes(tmp_path,monkeypatch):
    from photocluster.service import Service
    s=Service(tmp_path);calls=[];version=['auto-v1']
    monkeypatch.setattr(s,'scan_photos',lambda serial,items,processed,*a,**k:processed.extend(items))
    monkeypatch.setattr(auto,'model_identity',lambda:version[0])
    monkeypatch.setattr(auto,'cluster',lambda *a:(calls.append(True) or []))
    for _ in range(2):s.worker('test',photos(1),'subject','all',subject_engine='auto')
    assert len(calls)==1 and s.result['summary']['subject_engine']=='auto'
    version[0]='auto-v2';s.worker('test',photos(1),'subject','all',subject_engine='auto')
    assert len(calls)==2 and s.status['phase']=='done'
    assert s.result['summary']['subject_policy']==auto.VERSION


def test_older_subject_results_are_flagged_without_mutating_saved_groups(tmp_path,monkeypatch):
    import photocluster.app as module
    from photocluster.service import Service
    from fastapi.testclient import TestClient
    s=Service(tmp_path);monkeypatch.setattr(module,'service',s)
    summary=dict(mode='subject',subject_engine='auto')
    s.result={'groups':[],'summary':summary,'ungrouped':[]}
    with TestClient(module.app) as client:
        assert client.get('/api/groups').json()['summary']['recognition_outdated'] is True
        summary['subject_policy']=auto.VERSION
        assert client.get('/api/groups').json()['summary']['recognition_outdated'] is False
    assert 'recognition_outdated' not in summary


@pytest.mark.parametrize('valid',[True,False])
def test_router_checksum_before_loading(tmp_path,monkeypatch,valid):
    from scripts import setup_subject_auto as setup
    import sys
    p=tmp_path/'router.onnx';p.write_bytes(b'old');monkeypatch.setattr(setup,'MODEL',p)
    monkeypatch.setattr(setup,'SHA256',hashlib.sha256(b'new' if valid else b'wrong').hexdigest())
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:io.BytesIO(b'new')))
    loaded=[]
    monkeypatch.setitem(sys.modules,'onnxruntime',SimpleNamespace(disable_telemetry_events=lambda:None,InferenceSession=lambda *a,**k:loaded.append(True)))
    if valid:setup.install_router();assert p.read_bytes()==b'new' and loaded
    else:
        with pytest.raises(RuntimeError):setup.install_router()
        assert p.read_bytes()==b'old' and not loaded
    assert not p.with_suffix('.download').exists()


def test_optional_actual_router():
    if not auto.MODEL.exists():pytest.skip('Optional routing model not installed')
    scores=auto.routing_scores([Image.new('RGB',(64,64),'red')])
    assert scores.shape==(1,5) and np.isfinite(scores).all()
    assert float(scores.sum())==pytest.approx(1,abs=1e-4)


def test_postpass_reselects_reference_and_rewrites_direct_scores(monkeypatch):
    angles=[0,1.4,.6,.8]
    cs=[cv(x) for x in angles];gs=[gv(0)]*4;masks=[np.array([True])]*4
    prepare(monkeypatch,gs,cs,masks)
    p=photos(4)
    groups=auto.cluster(p,None)
    assert len(groups)==1 and len(groups[0])==4
    ref=groups[0][0]
    assert ref['key'] in ('2','3') and ref['relation']=='reference'
    for member in groups[0][1:]:
        r=int(ref['key']);i=int(member['key'])
        match=auto.verify_pair(gs[r],gs[i],masks[r],masks[i],cs[r],cs[i],.72)
        assert match is not None
        assert member['score']==round(min(match[1][0],.999),4)
        assert (member['reference_frame'],member['match_frame'])==match[1][1:]
        assert member['relation']=='subject'
    p[1]['album']=p[3]['album']='/other'
    assert [set(x['album'] for x in g) for g in auto.cluster(p,None,scope='album')]==[{'/test'},{'/other'}]


def test_cancel_during_postpass_does_not_return_partial_groups(monkeypatch):
    prepare(monkeypatch,[gv(0)]*4,[cv(x) for x in (0,1.4,.6,.8)],[np.array([True])]*4)
    stopped=[False]
    def progress(done,total,phase):
        if phase=='subject_consolidate':stopped[0]=True
    assert auto.cluster(photos(4),None,progress=progress,cancelled=lambda:stopped[0]) is None
