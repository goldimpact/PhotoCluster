import hashlib
import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from photocluster import subject, character, subject_auto as auto


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


def test_one_scan_groups_general_and_specialist_matches_without_partitioning(monkeypatch):
    gs=[gv(x) for x in (0,.2,1.8,3)]
    cs=[cv(x) for x in (0,0,0,.2)]
    requested=prepare(monkeypatch,gs,cs,[np.array([False]),np.array([True]),np.array([True]),np.array([True])])
    groups=auto.cluster(photos(4),None)
    assert [{p['key'] for p in g} for g in groups]==[{'0','1'},{'2','3'}]
    assert requested==['1','2','3']
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
