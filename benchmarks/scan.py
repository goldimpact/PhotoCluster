"""Read-only phone I/O and feature-extraction benchmark, no originals on disk."""
import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photocluster import adb, vision
from photocluster.config import DATA


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--count',type=int,default=36)
    parser.add_argument('--baseline',type=Path,help='Optional local Python baseline snapshot')
    args=parser.parse_args()
    catalog=json.loads((DATA/'catalog.json').read_text('utf-8'))
    candidates=[p for p in catalog['photos'] if p['path'].lower().endswith(('.jpg','.jpeg')) and p['size'] < 8*1024**2]
    # Interleave camera and other pictures to represent both decode workloads.
    camera=[p for p in candidates if p['album'].endswith('/Camera')]
    other=[p for p in candidates if not p['album'].endswith('/Camera')]
    photos=[p for pair in zip(camera,other) for p in pair][:args.count]
    serial=catalog['serial']
    t=time.perf_counter()
    individual=[(p,adb.read_photo(serial,p['path'])) for p in photos]
    single_seconds=time.perf_counter()-t
    t=time.perf_counter()
    batched=list(adb.read_batch(serial,photos))
    batch_seconds=time.perf_counter()-t
    assert {p['key']:raw for p,raw in individual}=={p['key']:raw for p,raw in batched}
    versions=[('new',vision,8)]
    if args.baseline:
        spec=importlib.util.spec_from_file_location('baseline',args.baseline)
        baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        versions.insert(0,('old',baseline,3))
    output=DATA/'benchmarks/scan';output.mkdir(parents=True,exist_ok=True)
    results={}
    for name,module,workers in versions:
        def process(item):
            p,raw=item
            return module.features(raw,output/f'{name}-{p["key"]}.jpg')
        t=time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            feats=list(pool.map(process,individual))
        results[name]=time.perf_counter()-t
        assert all((f['width'],f['height'])==(p['width'],p['height']) or (f['height'],f['width'])==(p['width'],p['height']) for f,(p,_) in zip(feats,individual))
    result=dict(count=len(photos),bytes=sum(len(raw) for _,raw in individual),
                individual_read_seconds=single_seconds,batch_read_seconds=batch_seconds,
                old_features_seconds=results.get('old'),new_features_seconds=results['new'])
    (DATA/'benchmarks/scan.json').write_text(json.dumps(result),'utf-8')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
