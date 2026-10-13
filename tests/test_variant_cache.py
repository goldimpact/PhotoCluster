from pathlib import Path
from threading import Event

import numpy as np
import pytest

from photocluster import variants, acceleration
from photocluster.variant_cache import MetadataCache
from test_vision import scene, feature


def test_index_reuses_arrays_without_reopening_archives(tmp_path, monkeypatch):
    p=feature(scene(),tmp_path/'one.jpg');stats={}
    first=variants.prepare_all([p],None,lambda:False,stats=stats)
    assert stats==dict(feature_cached=0,feature_computed=1)
    with np.load(first[0]['variant_path']) as d:
        assert set(d.files)>={'image0','d0_0','p0_0','hashes','sha','version'}
    monkeypatch.setattr(variants,'prepare',lambda *a:pytest.fail('Must use metadata index'))
    assert variants.prepare_all([p],None,lambda:False,stats=stats)==first
    assert stats==dict(feature_cached=1,feature_computed=0)


def test_index_checks_sha_sampling_version_archive_stat_and_presence(tmp_path):
    p=feature(scene(),tmp_path/'one.jpg')
    result=variants.prepare_all([p],None,lambda:False)[0]
    cache=MetadataCache(tmp_path,variants.VERSION)
    assert cache.get(p)==result
    assert cache.get(dict(p,sha256='changed')) is None
    assert cache.get(dict(p,animated=True)) is None
    cache.close()
    cache=MetadataCache(tmp_path,variants.VERSION+1);assert cache.get(p) is None;cache.close()
    cache=MetadataCache(tmp_path,variants.VERSION)
    before=cache.identity(p)
    path=Path(result['variant_path']);path.write_bytes(b'interrupted')
    assert cache.get(p) is None
    cache.put(result,before);assert cache.get(p) is None
    path.unlink();assert cache.get(p) is None
    cache.close()


def test_legacy_cache_migration_force_and_corrupt_archive_recovery(tmp_path,monkeypatch):
    p=feature(scene(),tmp_path/'one.jpg');old=variants.prepare(p);stats={}
    original=variants.vision.comparison_image
    monkeypatch.setattr(variants.vision,'comparison_image',lambda *a:pytest.fail('Legacy archive already usable'))
    assert variants.prepare_all([p],None,lambda:False,stats=stats)==[old]
    assert stats['feature_cached']==1
    monkeypatch.setattr(variants.vision,'comparison_image',original)
    assert variants.prepare_all([p],None,lambda:False,force=True,stats=stats)==[old]
    assert stats['feature_computed']==1
    Path(old['variant_path']).write_bytes(b'incomplete zip')
    assert variants.prepare_all([p],None,lambda:False,stats=stats)==[old]
    assert stats['feature_computed']==1


def test_completion_queue_reports_fast_items_before_slow_first_item(tmp_path,monkeypatch):
    release=Event();seen=[]
    ps=[dict(key=str(i),sha256=str(i),feature_path=str(tmp_path/f'{i}.npz')) for i in range(12)]
    monkeypatch.setattr(acceleration,'workers',lambda:2)
    def prepare(p,force,stats):
        if p['key']=='0':assert release.wait(5),'queue waited for first slow task'
        stats['cached']=False
        return dict(p,hashes=[],signatures=[])
    monkeypatch.setattr(variants,'prepare',prepare)
    def progress(done,total,phase):
        seen.append(done)
        if done>=5:release.set()
    result=variants.prepare_all(ps,progress,lambda:False)
    assert [p['key'] for p in result]==[p['key'] for p in ps]
    assert seen==list(range(13))


def test_cancel_bounds_admitted_work_and_leaves_completed_cache_usable(tmp_path,monkeypatch):
    stopped=[False]
    monkeypatch.setattr(acceleration,'workers',lambda:2)
    p=feature(scene(),tmp_path/'one.jpg')
    def progress(done,total,phase):
        if done:stopped[0]=True
    assert variants.prepare_all([p]*100,progress,lambda:stopped[0]) is None
    stopped[0]=False
    stats={};assert variants.prepare_all([p],None,lambda:False,stats=stats)
    assert stats['feature_cached']==1


def test_duplicate_worker_requests_reuse_one_complete_archive(tmp_path,monkeypatch):
    monkeypatch.setattr(acceleration,'workers',lambda:4)
    p=feature(scene(),tmp_path/'duplicate.jpg');calls=[]
    original=variants.vision.comparison_image
    def decode(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(variants.vision,'comparison_image',decode)
    values=variants.prepare_all([p]*24,None,lambda:False)
    assert len(values)==24 and all(v==values[0] for v in values)
    assert len(calls)==1
    with np.load(values[0]['variant_path']) as data:assert str(data['sha'])==p['sha256']


def test_all_cached_geometry_verdicts_do_not_unpack_query(tmp_path,monkeypatch):
    from photocluster import vision
    from photocluster.pair_cache import PairCache
    ps=[dict(key=str(i),sha256=str(i),hashes=[1],signatures=[],album='a',
             width=10,height=10,sharpness=2-i,size=10,variant_path='must-not-open') for i in range(2)]
    cache=PairCache(tmp_path/'pairs.sqlite3','test')
    ids,b,_=cache.query([ps[0]],ps[1]);cache.save(ids,b,[(.9,'cached')])
    monkeypatch.setattr(variants,'load',lambda *a:pytest.fail('Cached verdict needs no descriptor archive'))
    try:
        groups=vision.cluster(ps,'variants',pair_cache=cache)
        assert len(groups)==1 and len(groups[0])==2
    finally:cache.close()


def test_failed_archive_write_preserves_previous_complete_cache(tmp_path,monkeypatch):
    p=feature(scene(),tmp_path/'one.jpg');result=variants.prepare(p)
    path=Path(result['variant_path']);before=path.read_bytes()
    def fail(*args,**kwargs):raise OSError('Synthetic disk error')
    monkeypatch.setattr(np.lib.format,'write_array',fail)
    with pytest.raises(OSError,match='Synthetic'):
        variants.prepare(p,force=True)
    assert path.read_bytes()==before and not list(tmp_path.glob('*.tmp'))
