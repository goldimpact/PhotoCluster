import hashlib
import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from photocluster import character, subject
from photocluster.service import Service


def vector(angle):
    x=np.zeros((1,768),np.float32);x[0,:2]=[np.cos(angle),np.sin(angle)]
    return x


def photos():
    return [dict(key=str(i),sha256=str(i),album='/test',size=100-i,width=100,height=100,sharpness=100-i) for i in range(3)]


def test_upstream_distance_scale_and_direct_reference(monkeypatch):
    values=[vector(a) for a in (0,.7,1.4)]
    score,_,_=character.similarity(values[0],values[1])
    assert 1-score==pytest.approx((1-np.cos(.7))/2,abs=1e-6)
    monkeypatch.setattr(character,'vectors',lambda *args:values)
    groups=character.cluster(photos(),None)
    assert [[p['key'] for p in g] for g in groups]==[['0','1']]
    assert groups[0][1]['relation']=='character'
    assert character.cluster(photos(),None,cancelled=lambda:True) is None


def test_cross_media_frames_and_album_scope(monkeypatch):
    p=photos();p[1].update(animated=True,album='/other');p[2]['media_type']='video'
    monkeypatch.setattr(character,'vectors',lambda *args:[vector(0),np.concatenate([vector(2),vector(.1)]),vector(.2)])
    groups=character.cluster(p,None)
    assert len(groups[0])==3 and groups[0][1]['match_frame']==1
    groups=character.cluster(p,None,scope='album')
    assert {x['key'] for x in groups[0]}=={'0','2'}


def test_copy_of_nonreference_does_not_claim_identical_to_reference(monkeypatch):
    p=photos();p[2]['sha256']=p[1]['sha256']
    monkeypatch.setattr(character,'vectors',lambda *args:[vector(0),vector(.7),vector(.7)])
    group=character.cluster(p,None)[0]
    assert group[2]['score']==group[1]['score']<1
    assert group[2]['relation']=='character'


def test_engine_cache_separation_and_version_change(tmp_path,monkeypatch):
    s=Service(tmp_path);items=photos();calls=[];version=['ccip-v1']
    monkeypatch.setattr(s,'scan_photos',lambda serial,items,processed,*a,**k:processed.extend(items))
    monkeypatch.setattr(subject,'model_identity',lambda:'dino-v1')
    monkeypatch.setattr(character,'model_identity',lambda:version[0])
    def cluster(*args):calls.append(True);return []
    monkeypatch.setattr(subject,'cluster',cluster);monkeypatch.setattr(character,'cluster',cluster)
    for engine in ('general','anime','anime'):
        s.worker('test',items,'subject','all',subject_engine=engine)
        assert s.status['phase']=='done'
    assert len(calls)==2 and s.result['summary']['subject_engine']=='anime'
    version[0]='ccip-v2';s.worker('test',items,'subject','all',subject_engine='anime')
    assert len(calls)==3


def test_character_features_reuse_and_force(tmp_path,monkeypatch):
    version=['first'];calls=[]
    monkeypatch.setattr(character,'model_identity',lambda:version[0])
    monkeypatch.setattr(subject,'frames',lambda *a:[Image.new('RGB',(30,40))])
    monkeypatch.setattr(character,'encode',lambda *a:(calls.append(True) or vector(0)))
    for force in (False,False,True):character.vectors(photos()[:1],tmp_path,None,lambda:False,force)
    assert len(calls)==2
    version[0]='new';character.vectors(photos()[:1],tmp_path,None,lambda:False,False)
    assert len(calls)==3


@pytest.mark.parametrize('valid',[True,False])
def test_character_download_checksum_and_preservation(tmp_path,monkeypatch,valid):
    from scripts import setup_character as setup
    import sys
    path=tmp_path/'model.onnx';path.write_bytes(b'old')
    monkeypatch.setattr(setup,'MODEL',path)
    monkeypatch.setattr(setup,'SHA256',hashlib.sha256(b'new' if valid else b'wrong').hexdigest())
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:io.BytesIO(b'new')))
    loaded=[]
    monkeypatch.setitem(sys.modules,'onnxruntime',SimpleNamespace(disable_telemetry_events=lambda:None,InferenceSession=lambda *a,**k:loaded.append(True)))
    if valid:
        setup.install();assert path.read_bytes()==b'new' and loaded
    else:
        with pytest.raises(RuntimeError):setup.install()
        assert path.read_bytes()==b'old' and not loaded
    assert not path.with_suffix('.download').exists()


def test_optional_real_model_and_preprocess():
    if not character.MODEL.exists():pytest.skip('Optional CCIP model not installed')
    images=[Image.new('RGB',(90,160),'red'),Image.new('RGB',(180,120),'blue')]
    v=character.encode(images)
    assert v.shape==(2,768) and np.isfinite(v).all()
    np.testing.assert_allclose(np.linalg.norm(v,axis=1),1,atol=1e-5)


def test_subject_engine_api_validation():
    from photocluster.app import Scan,SubjectModelInstall
    from pydantic import ValidationError
    assert Scan(albums=[],mode='subject',subject_engine='anime').subject_engine=='anime'
    with pytest.raises(ValidationError):SubjectModelInstall(engine='unknown')
