import json
from pathlib import Path

import pytest

from photocluster.cache import CacheManager, summary
from photocluster.operations import Operations
from photocluster.service import Service


def library(tmp_path):
    s=Service(tmp_path); key='a'*64
    s.catalog={'serial':'test-device','photos':[]};s.save('catalog.json',s.catalog)
    s.result={'groups':[{'id':1,'photos':[]}],'summary':{'mode':'subject'}};s.save('groups.json',s.result)
    (s.thumbs/(key+'.jpg')).write_bytes(b'preview')
    (s.thumbs/(key+'.npz')).write_bytes(b'features')
    (s.thumbs/'notes.txt').write_text('user-owned unknown file')
    (s.thumbs/'subject-perceptual.sqlite3').write_bytes(b'optional feature cache')
    (s.thumbs/'subject-complementary.sqlite3').write_bytes(b'optional complementary cache')
    (s.thumbs/'subject-identity-refine.sqlite3').write_bytes(b'optional larger identity cache')
    (s.thumbs/'subject-domain-refine.sqlite3').write_bytes(b'optional domain cache')
    (s.thumbs/'subject-local-context.sqlite3').write_bytes(b'optional local context cache')
    (s.thumbs/'subject-identity-extra.sqlite3').write_bytes(b'optional combined identity cache')
    (s.thumbs/'variant-index.sqlite3').write_bytes(b'variant metadata index')
    (s.data/'matches').mkdir();(s.data/'matches'/(key+'.json')).write_text('{}')
    (s.data/'models').mkdir();(s.data/'models/model.onnx').write_bytes(b'model')
    (s.data/'operations.jsonl').write_text('journal')
    (s.data/'desktop-settings.json').write_text('{}')
    with s.connect() as con:con.execute('INSERT INTO features VALUES (?,?)',(key,json.dumps({'sha256':'hash'})))
    operations=Operations(s);operations.plans['old']={}
    return s,CacheManager(s,operations),key


@pytest.mark.parametrize('scope',['results','analysis','all'])
def test_cleanup_scopes_preserve_phone_models_unknown_files_and_journal(tmp_path,scope,monkeypatch):
    s,m,key=library(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('Cache cleanup must not contact phone')
    monkeypatch.setattr('photocluster.adb.run',forbidden)
    plan=m.preview(scope)
    assert plan['files']>=2
    assert s.result['summary']  # Preview has no mutations.
    result=m.execute(plan['token'])
    assert result['failed']==0 and s.result['summary'] is None
    assert not m.operations.plans
    assert (s.thumbs/(key+'.jpg')).exists()==(scope=='results')
    assert (s.thumbs/'subject-perceptual.sqlite3').exists()==(scope=='results')
    assert (s.thumbs/'subject-complementary.sqlite3').exists()==(scope=='results')
    assert (s.thumbs/'subject-identity-refine.sqlite3').exists()==(scope=='results')
    assert (s.thumbs/'subject-domain-refine.sqlite3').exists()==(scope=='results')
    assert (s.thumbs/'subject-local-context.sqlite3').exists()==(scope=='results')
    assert (s.thumbs/'subject-identity-extra.sqlite3').exists()==(scope=='results')
    assert (s.thumbs/'variant-index.sqlite3').exists()==(scope=='results')
    with s.connect() as con:assert bool(con.execute('SELECT * FROM features').fetchall())==(scope=='results')
    assert (s.catalog['serial'] is None)==(scope=='all')
    for name in ('models/model.onnx','operations.jsonl','desktop-settings.json','thumbnails/notes.txt'):
        assert (s.data/name).exists()
    with pytest.raises(ValueError):m.execute(plan['token'])


def test_busy_and_expired_cleanup_cannot_mutate(tmp_path,monkeypatch):
    s,m,key=library(tmp_path);plan=m.preview('all')
    s.status['running']=True
    with pytest.raises(ValueError):m.execute(plan['token'])
    assert (s.thumbs/(key+'.jpg')).exists()
    s.status['running']=False;s.sync_status['running']=True
    with pytest.raises(ValueError):m.preview('all')
    s.sync_status['running']=False
    scope,created=m.plans[plan['token']];m.plans[plan['token']]=(scope,created-301)
    with pytest.raises(ValueError):m.execute(plan['token'])
    assert s.result['summary']


def test_symlink_target_is_refused_before_any_cleanup(tmp_path):
    s,m,key=library(tmp_path/'cache');outside=tmp_path/'outside';outside.write_bytes(b'private')
    link=s.thumbs/('b'*64+'.jpg')
    try:link.symlink_to(outside)
    except OSError:pytest.skip('Symlinks unavailable for this account')
    with pytest.raises(ValueError):m.preview('all')
    assert outside.read_bytes()==b'private' and s.result['summary']


def test_api_requires_valid_scope_and_one_time_preview(tmp_path,monkeypatch):
    import photocluster.app as module
    from fastapi.testclient import TestClient
    s,m,key=library(tmp_path)
    monkeypatch.setattr(module,'service',s);monkeypatch.setattr(module,'cache_manager',m)
    with TestClient(module.app) as client:
        assert client.get('/api/cache').json()['categories']['analysis']['bytes']>0
        assert client.post('/api/cache/preview',json={'scope':'../models'}).status_code==422
        assert client.post('/api/cache/clear',json={'token':'invented'}).status_code==409
        token=client.post('/api/cache/preview',json={'scope':'results'}).json()['token']
        assert client.post('/api/cache/clear',json={'token':token}).status_code==200
        assert client.post('/api/cache/clear',json={'token':token}).status_code==409


def test_usage_tolerates_sqlite_checkpoint_removing_wal(tmp_path,monkeypatch):
    s,m,key=library(tmp_path)
    import photocluster.cache as cache
    original=cache.inventory
    def checkpoint(service):
        paths=original(service)
        gone=tmp_path/'disappeared.sqlite3-wal'
        paths['analysis'].append(gone)
        return paths
    monkeypatch.setattr(cache,'inventory',checkpoint)
    assert summary(s)['categories']['analysis']['bytes']>0
