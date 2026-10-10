import importlib
from unittest.mock import Mock
import numpy as np
import pytest
from fastapi.testclient import TestClient
from photocluster import variants,geometry_gpu
from photocluster.service import Service
from photocluster.rules import normalize_rules
from test_vision import scene,feature
from test_variants import transformed


def test_api_rules_validation_and_forwarding(monkeypatch):
    module=importlib.import_module('photocluster.app');start=Mock(return_value={'running':True})
    monkeypatch.setattr(module.service,'start',start)
    with TestClient(module.app) as client:
        assert client.post('/api/scan',json={'albums':['/a'],'rules':{'warp':True,'mirror':False}}).status_code==200
        assert start.call_args.args[-1]==dict(warp=True,mirror=False,perspective=True)
        assert client.post('/api/scan',json={'albums':['/a'],'rules':{'warp':'yes'}}).status_code==422
        assert client.post('/api/scan',json={'albums':['/a'],'rules':{'typo':True}}).status_code==422


def test_rule_combinations_isolate_match_and_pair_caches(tmp_path,monkeypatch):
    service=Service(tmp_path);p=dict(key='p',sha256='h',size=1)
    monkeypatch.setattr(service,'scan_photos',lambda serial,photos,processed,errors,started:processed.extend(photos))
    calls=[]
    def cluster(photos,scope,progress,cancelled,force,cache,rules):
        ids,b,found=cache.query([p],p);calls.append((dict(rules),bool(found)))
        cache.save(ids,b,[None]);return []
    monkeypatch.setattr(variants,'cluster',cluster)
    for rules in ({'warp':False},{'warp':True},{'mirror':False},{'perspective':False},{'warp':False}):
        service.worker('s',[p],'variants','all',rules=rules)
        assert service.status['phase']=='done'
        assert service.result['summary']['rules']==normalize_rules(rules)
    assert len(calls)==4 and not any(hit for _,hit in calls)
    assert service.status['reused_matches']


def test_mirror_disabled_skips_flipped_descriptors(tmp_path,monkeypatch):
    a=variants.prepare(feature(scene(),tmp_path/'a.jpg'));b=variants.prepare(feature(scene(123),tmp_path/'b.jpg'))
    flips=[]
    monkeypatch.setattr(variants,'frame_match',lambda a,b,i,j,flip,*args:flips.append(flip))
    variants.compare(a,b,rules={'mirror':False});assert flips==[0]
    flips.clear();variants.compare(a,b,rules={'mirror':True});assert flips==[0,1]


def test_affine_selection_and_warp_branch_skipped(tmp_path,monkeypatch):
    a=variants.prepare(feature(scene(),tmp_path/'a.jpg'));b=variants.prepare(feature(transformed(scene(),'affine'),tmp_path/'b.jpg'))
    monkeypatch.setattr(variants.cv2,'findHomography',Mock(side_effect=AssertionError('perspective disabled')))
    assert variants.compare(a,b,rules={'perspective':False,'warp':False})
    # Force structural rejection; warp disabled must not enter residual interpolation.
    monkeypatch.setattr(variants,'tile_score',lambda *args:None)
    monkeypatch.setattr(variants.np,'rint',Mock(side_effect=AssertionError('warp reached')))
    assert variants.compare(a,b,rules={'perspective':False,'warp':False}) is None
    with pytest.raises(AssertionError,match='warp reached'):
        variants.compare(a,b,rules={'perspective':False,'warp':True})


def test_gpu_mirror_flag_excludes_flipped_inputs():
    from photocluster.acceleration import cuda
    if cuda() is None:pytest.skip('optional CUDA')
    rng=np.random.default_rng(5);d=rng.integers(0,256,(20,128)).astype(np.float32)
    # No flipped array: GPU path must not access or calculate it.
    result=geometry_gpu.match_sources([{'count':1,'d0_0':d}],{'count':1,'d0_0':d},mirror=False)
    assert result is not None and set(result[0])=={(0,0,0)}
