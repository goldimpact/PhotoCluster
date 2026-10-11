"""Read cached features only. Never mutates phone files or saved UI results."""
import argparse
import cProfile
import hashlib
import json
import random
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',default='variants',choices=['variants','content','strong'])
    parser.add_argument('--threads',type=int,default=0)
    parser.add_argument('--workers',type=int,default=0)
    parser.add_argument('--limit',type=int,default=240)
    parser.add_argument('--output',required=True)
    parser.add_argument('--profile',action='store_true')
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--pair-cache',default='')
    parser.add_argument('--warp',action='store_true',help='Enable the optional high-cost warp verification')
    args=parser.parse_args()
    from photocluster.service import Service
    from photocluster.config import DATA
    from photocluster import variants,semantic,vision
    if args.baseline and args.mode=='content':
        import importlib.util
        spec=importlib.util.spec_from_file_location('photocluster.baseline_semantic',DATA/'benchmarks/hardware/semantic.py')
        semantic=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantic)
    elif args.baseline and args.mode=='variants':
        import importlib.util
        spec=importlib.util.spec_from_file_location('photocluster.baseline_variants',DATA/'benchmarks/geometry/variants.py')
        original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
        variants.frame_match=original.frame_match
        variants.tile_score=original.tile_score
        variants.compare_candidates=lambda reps,p,c,e,cache=None,rules=None:original.compare_candidates(reps,p,c,e)
    from threadpoolctl import threadpool_limits,threadpool_info
    if args.threads:threadpool_limits(args.threads,user_api='blas')
    if args.workers:
        from concurrent.futures import ThreadPoolExecutor
        vision.ThreadPoolExecutor=lambda **kw:ThreadPoolExecutor(max_workers=args.workers)
        variants.ThreadPoolExecutor=lambda **kw:ThreadPoolExecutor(max_workers=args.workers)
    s=Service()
    with s.connect() as con:features={k:json.loads(v) for k,v in con.execute('SELECT key,payload FROM features')}
    photos=[dict(p,**features[p['key']]) for p in s.catalog['photos'] if p['key'] in features]
    if args.limit:
        rng=random.Random(17);sample=[]
        counts=[args.limit*3//4,args.limit//6];counts.append(args.limit-sum(counts))
        for kind,count in zip(('image','gif','video'),counts):
            pool=[p for p in photos if ('video' if p.get('media_type')=='video' else 'gif' if p.get('animated') else 'image')==kind]
            sample.extend(rng.sample(pool,min(count,len(pool))))
        photos=sample
    phases={};start=time.perf_counter();cpu=time.process_time();last_report=[start]
    def report(done,total,phase='match'):
        if phase not in phases:
            phases[phase]=time.perf_counter()-start
            print(phase,round(phases[phase],3),flush=True)
        if time.perf_counter()-last_report[0]>=15:
            print('progress',phase,done,total,round(time.perf_counter()-start,1),flush=True)
            last_report[0]=time.perf_counter()
    profile=cProfile.Profile()
    if args.profile:profile.enable()
    if args.mode=='variants':
        from photocluster.pair_cache import PairCache
        from photocluster.rules import normalize_rules,pair_version
        rules=normalize_rules({'warp':args.warp})
        cache=PairCache(args.pair_cache,pair_version(rules)) if args.pair_cache else None
        try:groups=variants.cluster(photos,'all',report,lambda:False,pair_cache=cache,rules=rules)
        finally:
            if cache:
                print('pair cache',dict(hits=cache.hits,computed=cache.computed),flush=True)
                cache.close()
    elif args.mode=='content':groups=semantic.cluster(photos,s.thumbs,progress=report)
    else:groups=vision.cluster(photos,'strong',progress=report)
    elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu
    if args.profile:
        profile.disable();profile.dump_stats(args.output+'.prof')
    membership=sorted(sorted(p['key'] for p in g) for g in groups)
    result=dict(mode=args.mode,files=len(photos),seconds=elapsed,cpu_seconds=cpu,
                average_cpu_cores=cpu/elapsed,phases=phases,groups=len(groups),members=membership,
                digest=hashlib.sha256(json.dumps(membership).encode()).hexdigest(),
                threadpools=threadpool_info())
    from photocluster.acceleration import hardware_info
    result['hardware']=hardware_info()
    Path(args.output).write_text(json.dumps(result,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('members','threadpools')}),flush=True)


if __name__=='__main__':main()
