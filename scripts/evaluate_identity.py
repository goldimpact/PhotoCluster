"""Offline labelled-pair comparison. No downloads, phone access or cache mutation.

Input JSON: {"items":[{"id":"a","path":"a.jpg"}, ...],
             "pairs":[{"a":"a","b":"b","same":true}, ...]}
Paths are relative to the manifest. Keep real manifests and output under data/.
Pair labels should include same-character/different-style and different-character/
similar-colour examples. An upstream demonstration is not an independent benchmark.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photocluster import character,subject


def counts(rows,field):
    return {name:sum(bool(row['same'])==truth and bool(row[field])==pred for row in rows)
            for name,truth,pred in [('tp',True,True),('fn',True,False),('fp',False,True),('tn',False,False)]}


def evaluate(manifest):
    manifest=Path(manifest);data=json.loads(manifest.read_text('utf-8'))
    ids=[x['id'] for x in data['items']]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate item IDs')
    features={};timings={'dino':0.,'ccip':0.}
    for item in data['items']:
        with Image.open(manifest.parent/item['path']) as source:im=source.convert('RGB')
        start=time.perf_counter();dino=subject.encode([im]);timings['dino']+=time.perf_counter()-start
        start=time.perf_counter();ccip=character.encode([im]);timings['ccip']+=time.perf_counter()-start
        features[item['id']]=(dino,ccip)
    rows=[]
    for pair in data['pairs']:
        if type(pair['same']) is not bool:raise ValueError('Pair labels must be boolean')
        a,b=features[pair['a']],features[pair['b']]
        old=subject.similarity(a[0],b[0])[0];new=character.similarity(a[1],b[1])[0]
        rows.append(dict(a=pair['a'],b=pair['b'],same=pair['same'],dino_score=old,ccip_distance=1-new,
                         dino_match=old>=.72,ccip_match=new>=character.DEFAULT_THRESHOLD))
    return dict(models={'dino':subject.model_identity(),'ccip':character.model_identity()},
                thresholds={'dino':.72,'ccip_distance':character.DEFAULT_DISTANCE},seconds=timings,
                counts={'dino':counts(rows,'dino_match'),'ccip':counts(rows,'ccip_match')},pairs=rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifest');parser.add_argument('--output',required=True)
    args=parser.parse_args();result=evaluate(args.manifest)
    Path(args.output).write_text(json.dumps(result,indent=2),'utf-8')
    print(json.dumps({'counts':result['counts'],'seconds':result['seconds']},indent=2))
