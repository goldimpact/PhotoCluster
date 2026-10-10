import cv2
import numpy as np
import pytest
from concurrent.futures import ThreadPoolExecutor
from photocluster import acceleration,geometry_gpu,variants,vision
from photocluster.pair_cache import PairCache
from photocluster.index import PostingIndex
from test_vision import scene,feature
from test_variants import transformed


def test_fused_gpu_preserves_exact_matches_across_frames_and_blocks():
    if acceleration.cuda() is None:pytest.skip('CUDA optional')
    rng=np.random.default_rng(51);sources=[]
    target={'count':3}
    for j,n in enumerate((0,19,601)):
        target[f'd{j}_0']=rng.integers(0,256,(n,128)).astype(np.float32)
    for n in (14,357,603,33000):
        source={'count':1}
        for flip in range(2):
            a=rng.integers(0,256,(n,128)).astype(np.float32)
            a[:10]=target['d2_0'][:10]
            source[f'd0_{flip}']=a
        sources.append(source)
    target['d2_0'][0]=target['d2_0'][1]
    actual=geometry_gpu.match_sources(sources,target)
    assert actual is not None
    for s,maps in zip(sources,actual):
        for (i,j,flip),matches in maps.items():
            expected=vision.descriptor_matches(s[f'd{i}_{flip}'],target[f'd{j}_0']) if len(target[f'd{j}_0'])>=14 else []
            pack=lambda mm:[(m.queryIdx,m.trainIdx,m.distance) for m in mm]
            assert pack(expected)==pack(matches)


def test_packed_tiles_equal_individual_tile_scores():
    rng=np.random.default_rng(18)
    a=rng.integers(0,256,(384,384,3),dtype=np.uint8)
    for amount in (0,3,20,70):
        b=np.clip(a.astype(float)+rng.normal(0,amount,a.shape),0,255).astype(np.uint8)
        mask=rng.random((384,384))>.1;mask[:50]=False
        scores=[]
        for y in range(0,384,64):
            for x in range(0,384,64):
                m=mask[y:y+64,x:x+64]
                if m.mean()>=.75:
                    s,c=vision.structure(a[y:y+64,x:x+64],b[y:y+64,x:x+64],m)
                    scores.append(s if c<=.14 else 0)
        ss=np.asarray(scores)
        expected=float(np.mean(np.sort(ss)[len(ss)//4:])) if len(ss)>=12 and (ss>=.70).mean()>=.65 and np.median(ss)>=.78 else None
        actual=variants.tile_score(a,b,mask)
        if expected is None:assert actual is None
        else:assert actual==pytest.approx(expected,abs=2e-6)


def test_pair_cache_preserves_negative_and_positive_results(tmp_path,monkeypatch):
    a=variants.prepare(feature(scene(),tmp_path/'a.jpg'))
    b=variants.prepare(feature(transformed(scene(),'affine'),tmp_path/'b.jpg'))
    c=variants.prepare(feature(scene(123),tmp_path/'c.jpg'))
    path=tmp_path/'pairs.sqlite3'
    cache=PairCache(path,'test-v1')
    with ThreadPoolExecutor(2) as pool:
        first=variants.compare_candidates([a,c],b,[0,1],pool,cache)
    assert first[0] and first[1] is None
    cache.close()  # Same persistence path as cancellation cleanup.
    cache=PairCache(path,'test-v1')
    monkeypatch.setattr(variants,'_compare_candidates',lambda *args:pytest.fail('Must reuse completed verification'))
    second=variants.compare_candidates([a,c],b,[0,1],None,cache)
    assert first[0][0]==second[0][0] and second[1] is None and cache.hits==2
    _,_,found=cache.query([a,c],dict(b,sha256='changed'));assert not found
    cache.close()
    cache=PairCache(path,'test-v2');_,_,found=cache.query([a,c],b);assert not found;cache.close()


def test_fused_gpu_failure_uses_cpu(monkeypatch,tmp_path):
    a=variants.prepare(feature(scene(),tmp_path/'a.jpg'))
    b=variants.prepare(feature(transformed(scene(),'perspective'),tmp_path/'b.jpg'))
    monkeypatch.setattr(geometry_gpu,'match_sources',lambda *args,**kwargs:None)
    with ThreadPoolExecutor(2) as pool:
        assert list(variants.compare_candidates([a],b,[0],pool))[0]


def test_active_postings_preserve_full_candidate_votes():
    from collections import Counter
    rng=np.random.default_rng(28)
    photos=[dict(signatures=rng.integers(0,2**64-1,200,dtype=np.uint64).tolist()+[7,19]) for _ in range(180)]
    index=PostingIndex(photos);tables={};active=0
    for i,p in enumerate(photos):
        votes=Counter()
        for key in index.keys[i]:
            bucket=tables.get(int(key),[])
            if len(bucket)<=100:votes.update(bucket)
        expected=[j for j,count in sorted(votes.items(),key=lambda x:(-x[1],x[0])) if count>=4][:32]
        assert index.search(i,limit=32)==expected
        if i%3:
            index.add(i,active)
            for key in index.keys[i]:tables.setdefault(int(key),[]).append(active)
            active+=1
