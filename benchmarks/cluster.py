"""Reproducible cached-library benchmark; never changes phone files."""
import argparse
import cProfile
import hashlib
import importlib.util
import json
import pstats
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_photos(limit=0):
    catalog = json.loads((ROOT/'data/catalog.json').read_text('utf-8'))
    with sqlite3.connect(ROOT/'data/catalog.sqlite3') as con:
        cached = {key: json.loads(payload) for key, payload in con.execute('SELECT key,payload FROM features')}
    photos = [dict(p, **cached[p['key']]) for p in catalog['photos'] if p['key'] in cached]
    # Deterministic spread across the entire library, not only the oldest files.
    photos.sort(key=lambda p: hashlib.sha256(p['key'].encode()).digest())
    return photos[:limit] if limit else photos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--tag', default='run')
    args = parser.parse_args()
    if args.baseline:
        spec = importlib.util.spec_from_file_location('vision_baseline', ROOT/'data/benchmarks/vision_baseline.py')
        vision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vision)
    else:
        from photocluster import vision
    photos = load_photos(args.limit)
    profiler = cProfile.Profile()
    started = time.perf_counter()
    if args.profile:
        profiler.enable()
    groups = vision.cluster(photos, mode='strong', progress=lambda i,n: print(f'{i}/{n} {time.perf_counter()-started:.1f}s',flush=True) if i%500==0 else None)
    if args.profile:
        profiler.disable()
    elapsed = time.perf_counter()-started
    result = dict(seconds=elapsed, count=len(photos), groups=len(groups),
                  members=[sorted(p['key'] for p in group) for group in groups])
    target = ROOT/'data/benchmarks'/f'{args.tag}.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result), 'utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='members'}),flush=True)
    if args.profile:
        pstats.Stats(profiler).sort_stats('cumtime').print_stats(25)


if __name__ == '__main__':
    main()
