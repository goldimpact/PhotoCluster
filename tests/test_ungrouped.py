import importlib
from fastapi.testclient import TestClient
from photocluster.service import Service
from photocluster import vision, adb
from test_operations import setup


def test_unmatched_only_successful_current_scan(tmp_path,monkeypatch):
    service=Service(tmp_path)
    photos=[dict(key=k,sha256=k,size=10,path='/a/'+k,album='/a') for k in ('a','b','c')]
    service.catalog=dict(serial='s',photos=photos+[dict(key='outside')])
    def scan(serial,requested,processed,errors,started):
        processed.extend(photos);errors.append(dict(path='/a/broken',error='broken'))
    monkeypatch.setattr(service,'scan_photos',scan)
    monkeypatch.setattr(vision,'cluster',lambda *args,**kwargs:[[dict(p,score=1,reason='same') for p in photos[:2]]])
    service.worker('s',photos,'strong','all')
    assert service.status['phase']=='done'
    assert [p['key'] for p in service.result['ungrouped']]==['c']
    assert service.result['summary']['ungrouped']==1
    service.worker('s',photos,'strong','all')
    assert service.status['reused_matches']
    assert [p['key'] for p in service.result['ungrouped']]==['c']


def test_unmatched_global_sort_filter_and_paging(tmp_path,monkeypatch):
    module=importlib.import_module('photocluster.app');service=Service(tmp_path)
    photos=[dict(key=str(i),path=f'/a/{i}.jpg',album='/a' if i%2 else '/b',modified=i,size=i) for i in range(250)]
    service.result=dict(summary={'ungrouped':250},groups=[],ungrouped=photos)
    monkeypatch.setattr(module,'service',service)
    with TestClient(module.app) as client:
        data=client.get('/api/groups/0?page=2&sort=newest').json()
        assert data['total']==250 and len(data['photos'])==100
        assert data['photos'][0]['modified']==149
        assert data['reference_key'] is None
        assert client.get('/api/groups/0?page=99').json()['page']==3
        assert client.get('/api/groups/0?page=1&album=/a').json()['total']==125
        assert client.get('/api/groups?album=/b').json()['ungrouped']['count']==125
        assert len(client.get('/api/groups/0?sort=oldest').json()['photos'])==250


def test_delete_unmatched_and_changed_content_guard(setup,monkeypatch):
    s,ops,commands=setup
    s.result['ungrouped']=s.result['groups'].pop()['photos']
    monkeypatch.setattr('photocluster.operations.exists',lambda *args:False)
    plan=ops.prepare(['a'],'delete');assert not commands
    assert ops.execute(plan['token'])['succeeded']==1
    assert [p['key'] for p in s.result['ungrouped']]==['b']
    monkeypatch.setattr(adb,'read_photo',lambda *args:b'changed')
    assert ops.execute(ops.prepare(['b'],'delete')['token'])['succeeded']==0


def test_move_unmatched_updates_key_and_real_album(setup,monkeypatch):
    s,ops,_=setup;s.result['ungrouped']=s.result['groups'].pop()['photos']
    checks=iter([False,False,True]);monkeypatch.setattr('photocluster.operations.exists',lambda *args:next(checks))
    assert ops.execute(ops.prepare(['a'],'move','/storage/emulated/0/b')['token'])['succeeded']==1
    p=s.result['ungrouped'][0]
    assert p['key']!='a' and p['path']=='/storage/emulated/0/b/a.jpg'
    assert ops.prepare([p['key']],'delete')['items'][0]['source']==p['path']


def test_remaining_single_member_becomes_unmatched(setup,monkeypatch):
    s,ops,_=setup
    monkeypatch.setattr('photocluster.operations.exists',lambda *args:False)
    ops.execute(ops.prepare(['a'],'delete')['token'])
    assert s.result['groups']==[]
    assert s.result['ungrouped'][0]['key']=='b'


def test_refresh_prunes_unmatched_but_does_not_add_unscanned(tmp_path,monkeypatch):
    s=Service(tmp_path)
    p=dict(path='/storage/emulated/0/a/x.jpg',album='/storage/emulated/0/a',album_name='a',size=10,modified=1)
    p['key']=s.key('s',p)
    s.catalog=dict(serial='s',photos=[p])
    s.result=dict(summary={'serial':'s'},groups=[],ungrouped=[dict(p,sha256='old')])
    monkeypatch.setattr(adb,'inventory',lambda *args:[dict(p,modified=2)])
    s.refresh('s')
    assert not s.result['ungrouped'] and s.result['summary']['stale']
