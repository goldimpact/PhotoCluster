"""Evaluate saved offline groupings without loading models or touching a phone.

Input: {items:[{id,label?}], negatives:[[id,id]], runs:{name:[[id,...],...]}}.
Only explicit labels/negative edges are truth. Unknown items are reported as
unlabelled neighbors, not automatically as false positives. No transitive labels.
Private input and reports should stay in ignored data/.
"""
import argparse
from collections import Counter
import json
from pathlib import Path


def evaluate(data):
    items=data['items'];ids=[p['id'] for p in items]
    if any(not isinstance(k,str) or not k for k in ids) or len(set(ids))!=len(ids):
        raise ValueError('Media IDs must be unique nonempty strings; deduplicate snapshots first')
    labels={p['id']:p['label'] for p in items if p.get('label') is not None}
    if any(not isinstance(x,str) or not x for x in labels.values()):raise ValueError('Invalid identity label')
    identities=Counter(labels.values());known=set(ids);negative=set()
    for edge in data.get('negatives',[]):
        if len(edge)!=2 or edge[0]==edge[1] or not set(edge)<=known:raise ValueError('Invalid negative edge')
        a,b=edge
        if a in labels and b in labels and labels[a]==labels[b]:raise ValueError('Conflicting positive and negative labels')
        negative.add(tuple(sorted(edge)))
    output={}
    for name,groups in data['runs'].items():
        assigned={};counts=[];labelled_errors=0;unknown_edges=0
        for index,group in enumerate(groups):
            if not group:raise ValueError('Empty group')
            for key in group:
                if key not in known or key in assigned:raise ValueError('Unknown or multiply assigned media ID')
                assigned[key]=index
            count=Counter(labels[k] for k in group if k in labels);counts.append(count)
            labelled_count=sum(count.values());unlabelled=len(group)-labelled_count
            labelled_errors+=(labelled_count**2-sum(n*n for n in count.values()))//2
            unknown_edges+=unlabelled*labelled_count+unlabelled*(unlabelled-1)//2
        per_identity={}
        for label,total in identities.items():
            sizes=sorted((count[label] for count in counts if count[label]),reverse=True)
            ungrouped=sum(labels.get(k)==label and k not in assigned for k in known)
            sizes.extend([1]*ungrouped)
            per_identity[label]=dict(total=total,largest_group=max(sizes,default=0),
                fragments=len(sizes),sizes=sizes,retained_positive_pairs=sum(n*(n-1)//2 for n in sizes),
                possible_positive_pairs=total*(total-1)//2)
        negative_errors=sum(a in assigned and assigned.get(a)==assigned.get(b) for a,b in negative)
        output[name]=dict(identities=per_identity,known_cross_identity_pairs=labelled_errors,
            explicit_negative_pairs_merged=negative_errors,explicit_negative_pairs=len(negative),
            unlabelled_neighbor_pairs=unknown_edges,ungrouped=len(known-set(assigned)))
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.manifest.resolve()==args.output.resolve():raise ValueError('Output must not overwrite input')
    result=evaluate(json.loads(args.manifest.read_text('utf-8')))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
