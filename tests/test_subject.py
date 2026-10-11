import hashlib
import io
import math
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from photocluster import subject, semantic
from photocluster.service import Service


def descriptor(angle):
    v=np.zeros((1,6,384),np.float32)
    v[:,:,0]=math.cos(angle);v[:,:,1]=math.sin(angle)
    return v


def photos():
    return [dict(key=str(i),sha256=str(i),album='/test' if i!=1 else '/other',size=100-i,
                 width=100,height=100,sharpness=100-i) for i in range(3)]


def test_subject_grouping_requires_direct_match_not_chain_and_respects_scope(monkeypatch):
    # A-B and B-C match, A-C does not. C must not transitively enter A's group.
    values=[descriptor(x) for x in (0,.5,1.)]
    monkeypatch.setattr(subject,'vectors',lambda *args:values)
    groups=subject.cluster(photos(),None,threshold=.8)
    assert [[p['key'] for p in g] for g in groups]==[['0','1']]
    assert groups[0][1]['relation']=='subject'
    assert subject.cluster(photos(),None,scope='album',threshold=.8)==[]
    assert subject.cluster(photos(),None,cancelled=lambda:True) is None


def test_regional_match_survives_global_difference_but_background_alone_does_not():
    a=descriptor(0); b=descriptor(.8)
    b[:,2]=a[:,2]
    assert (a[:,0] @ b[:,0].T).item()<.72
    assert subject.similarity(a,b)[0]>.72
    b[:,0]=descriptor(1.5)[:,0]
    assert subject.similarity(a,b)[0]==-1


def test_subjects_match_across_still_animation_and_video_frames(monkeypatch):
    p=photos();p[1]['animated']=True;p[2]['media_type']='video'
    values=[descriptor(0),np.concatenate([descriptor(1.6),descriptor(.1)]),
            np.concatenate([descriptor(2),descriptor(.2)])]
    monkeypatch.setattr(subject,'vectors',lambda *args:values)
    groups=subject.cluster(p,None,threshold=.85)
    assert {x['key'] for x in groups[0]}=={'0','1','2'}
    assert groups[0][1]['match_frame']==1 and groups[0][2]['match_frame']==1


def test_feature_cache_invalidates_only_on_content_or_model_version(tmp_path,monkeypatch):
    p=photos()[:1];calls=[];version=['first']
    monkeypatch.setattr(subject,'model_identity',lambda:version[0])
    monkeypatch.setattr(subject,'frames',lambda *args:[Image.new('RGB',(20,20))])
    monkeypatch.setattr(subject,'encode',lambda imgs:(calls.append(True) or descriptor(0)))
    for _ in range(2):subject.vectors(p,tmp_path,None,lambda:False,False)
    assert len(calls)==1
    version[0]='second';subject.vectors(p,tmp_path,None,lambda:False,False)
    assert len(calls)==2
    p[0]['sha256']='changed';subject.vectors(p,tmp_path,None,lambda:False,False)
    assert len(calls)==3
    subject.vectors(p,tmp_path,None,lambda:False,True);assert len(calls)==4


@pytest.mark.parametrize('mode',['content','subject'])
def test_result_cache_tracks_model_version_without_reading_phone(tmp_path,monkeypatch,mode):
    model=subject if mode=='subject' else semantic
    s=Service(tmp_path);p=photos();version=['first'];calls=[]
    monkeypatch.setattr(s,'scan_photos',lambda serial,items,processed,errors,started,**kwargs:processed.extend(p))
    monkeypatch.setattr(model,'model_identity',lambda:version[0])
    monkeypatch.setattr(model,'cluster',lambda *args:(calls.append(True) or [[dict(x,score=.9,reason='test') for x in p]]))
    s.worker('test',p,mode,'all');assert s.status['phase']=='done'
    s.worker('test',p,mode,'all');assert len(calls)==1
    version[0]='second';s.worker('test',p,mode,'all');assert len(calls)==2
    assert s.result['groups'][0]['potential_bytes']==0


def test_model_hash_changes_for_replacement(tmp_path):
    p=tmp_path/'model';p.write_bytes(b'first')
    first=semantic.file_identity(p);p.write_bytes(b'second')
    assert semantic.file_identity(p)!=first


@pytest.mark.parametrize('valid',[True,False])
def test_subject_installer_verifies_before_replacement(tmp_path,monkeypatch,valid):
    from scripts import setup_subject as setup
    import sys
    p=tmp_path/'model.onnx';p.write_bytes(b'previous');payload=b'new test model'
    monkeypatch.setattr(setup,'MODEL',p)
    monkeypatch.setattr(setup,'SHA256',hashlib.sha256(payload if valid else b'bad').hexdigest())
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:io.BytesIO(payload)))
    loaded=[]
    monkeypatch.setitem(sys.modules,'onnxruntime',SimpleNamespace(disable_telemetry_events=lambda:None,InferenceSession=lambda *a,**k:loaded.append(True)))
    if valid:
        setup.install();assert p.read_bytes()==payload and loaded
    else:
        with pytest.raises(RuntimeError):setup.install()
        assert p.read_bytes()==b'previous' and not loaded
    assert not p.with_suffix('.download').exists()


def test_local_model_smoke_if_installed():
    if not subject.MODEL.exists():pytest.skip('Optional model not installed')
    # Shape/normalization check only; this is not a real character accuracy test.
    v=subject.encode([Image.new('RGB',(96,160),'red'),Image.new('RGB',(96,160),'blue')])
    assert v.shape==(2,6,384) and np.isfinite(v).all()
    np.testing.assert_allclose(np.linalg.norm(v,axis=-1),1,atol=1e-5)
