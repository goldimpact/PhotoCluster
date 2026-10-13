"""Recover isolated media using a fixed reference and frozen independent peers."""
import numpy as np

from .subject_merge import Cancelled

MAX_REFERENCE_FRAMES=8192
MAX_SINGLETONS=4096
MAX_VERIFY_PER_MEDIA=32
MAX_DENSITY_PEERS=64


def recover(groups,photos,characters,verify,scope='all',cancelled=lambda:False,progress=None):
    # Keep every pre-review member and reference immutable until all decisions
    # have finished; additions cannot become peers or grow a transitive chain.
    frozen=[list(g) for g in groups];targets={};streams=[]
    for j,g in enumerate(frozen):
        seen=set();peers=[]
        for i in g:
            sha=photos[i]['sha256']
            if sha not in seen:seen.add(sha);peers.append(i)
        if len(peers)>=4 and g[0] in characters:
            targets[j]=peers;streams.append((j,iter(characters[g[0]])))
    vectors=[];owners=[]
    while streams and len(vectors)<MAX_REFERENCE_FRAMES:
        remaining=[]
        for owner,stream in streams:
            if cancelled():raise Cancelled()
            try:vector=next(stream)
            except StopIteration:continue
            vectors.append(vector);owners.append(owner);remaining.append((owner,stream))
            if len(vectors)>=MAX_REFERENCE_FRAMES:break
        streams=remaining
    if not vectors:return frozen
    matrix=np.stack(vectors);owners=np.asarray(owners,np.int32)
    singles=[j for j,g in enumerate(frozen) if len(g)==1 and g[0] in characters][:MAX_SINGLETONS]
    budget=MAX_VERIFY_PER_MEDIA*sum(map(len,frozen));decisions=[];density_limits={}
    for done,j in enumerate(singles):
        if cancelled():raise Cancelled()
        i=frozen[j][0];best={}
        for offset in range(0,len(matrix),2048):
            if cancelled():raise Cancelled()
            scores=((1+characters[i]@matrix[offset:offset+2048].T)/2).max(axis=0)
            for at in np.flatnonzero(scores>=.82):
                other=int(owners[offset+at]);ref=frozen[other][0]
                if scope=='album' and photos[i]['album']!=photos[ref]['album']:continue
                best[other]=max(best.get(other,0),float(scores[at]))
        accepted=[];complete=True
        for target,_ in sorted(best.items(),key=lambda x:(-x[1],x[0]))[:4]:
            if budget<=0:complete=False;break
            ref=frozen[target][0];budget-=1;match=verify(ref,i)
            if match is None or not isinstance(match[2],dict) or match[2].get('kind') not in ('local_context','alternate_identity'):continue
            peers=targets[target];needed=max(3,(len(peers)+1)//2);hits=1
            adaptive=match[2]['kind']=='alternate_identity' and len(peers)<=MAX_DENSITY_PEERS
            if adaptive and target in density_limits:needed=min(needed,density_limits[target])
            # Exact copies cannot supply independent supporting observations.
            if photos[ref]['sha256']==photos[i]['sha256']:continue
            for at,peer in enumerate(peers[1:]):
                if cancelled():raise Cancelled()
                if hits>=needed:break
                # Defer quadratic target statistics until the candidate actually
                # needs them. Three is the minimum possible adaptive floor.
                floor=3 if adaptive and target not in density_limits else needed
                if hits+len(peers)-1-at<floor:break
                if photos[peer]['sha256']==photos[i]['sha256']:continue
                if budget<=0:complete=False;break
                budget-=1;hits+=verify(peer,i) is not None
            if not complete:break
            if hits<needed and hits>=3 and adaptive and target not in density_limits:
                requests=len(peers)*(len(peers)-1)
                if requests<budget:
                    degrees=[]
                    for left in peers:
                        degree=0
                        for right in peers:
                            if left==right:continue
                            if cancelled():raise Cancelled()
                            budget-=1;degree+=verify(left,right) is not None
                        degrees.append(degree)
                    density_limits[target]=max(3,int(np.ceil(np.quantile(degrees,.25))))
                    needed=min(needed,density_limits[target])
            if hits>=needed:accepted.append(target)
        # Never accept an unfinished uniqueness check when the budget expires.
        if complete and len(accepted)==1:decisions.append((j,accepted[0],i))
        if progress:progress(done+1,len(singles),'subject_singletons')
        if not complete:break
    result=[list(g) for g in frozen]
    for source,target,i in decisions:
        if cancelled():raise Cancelled()
        result[source]=[];result[target].append(i)
    return [g for g in result if g]
