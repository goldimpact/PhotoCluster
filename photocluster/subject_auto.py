"""One subject workflow with bounded, frame-specific supplemental evidence.

All media enter the general route. A style classifier can enable additional
character evidence; it never partitions the library or decides subject identity.
This is not universal identity recognition. Routing can be wrong, too.
"""
from contextlib import closing, nullcontext
from pathlib import Path
import sqlite3
import threading
from itertools import permutations
import heapq
from functools import lru_cache

from . import subject_merge, subject_singletons

import numpy as np
from PIL import Image

from . import subject, character, perceptual, complementary, identity_refine, domain_refine, local_context, identity_extra
from .config import DATA

MODEL=DATA/'models/subject-routing.onnx'
VERSION='subject-auto-deferred-identity-support-v17'
ROUTING_VERSION='mobilenetv3-v15-bilinear-half384-v1'
_REGION_ASSIGNMENTS=np.array(list(permutations(range(4))))
_session=None
_identity=None
_lock=threading.Lock()


def installed():
    return all(p.exists() for p in (MODEL,subject.MODEL,character.MODEL))


def routing_identity():
    from .semantic import file_identity
    return ROUTING_VERSION+':'+subject.VERSION+':'+file_identity(MODEL)


def model_identity():
    return ':'.join((VERSION,subject.model_identity(),character.model_identity(),routing_identity(),perceptual.model_identity(),complementary.model_identity(),identity_refine.model_identity(),domain_refine.model_identity(),local_context.model_identity(),identity_extra.model_identity()))


def session():
    global _session,_identity
    identity=routing_identity()
    with _lock:
        if _session is None or _identity!=identity:
            if not MODEL.exists():raise ValueError('请先准备主体识别资源')
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _identity=identity
    return _session


def routing_scores(images):
    model=session();result=[]
    for image in images:
        # Upstream generic classifier: RGB/BILINEAR 384, mean/std .5.
        a=np.asarray(image.convert('RGB').resize((384,384),Image.Resampling.BILINEAR),np.float32)/255
        batch=((a-.5)/.5).transpose(2,0,1)[None]
        outputs=dict(zip([x.name for x in model.get_outputs()],model.run(None,{model.get_inputs()[0].name:batch})))
        values=outputs.get('output')
        if values is None:values=next(iter(outputs.values()))
        values=np.asarray(values).reshape(-1)
        if len(values)!=5 or not np.isfinite(values).all():raise ValueError('Invalid routing model output')
        result.append(values)
    return np.asarray(result,np.float32)


def eligible(scores):
    # Upstream labels: 3d, bangumi, comic, illustration, not_painting.
    # Conservative supplemental gate, not a single-character detector. All
    # rejected/uncertain frames still participate in general visual matching.
    return scores[:,[0,1,3]].sum(axis=1)>=.8


def load_routes(photos,thumbs,progress,cancelled,force):
    from .frame_policy import feature_identity
    result=[];model=routing_identity()
    with closing(sqlite3.connect(Path(thumbs)/'subject-routing.sqlite3',timeout=30)) as con,con:
        con.execute('CREATE TABLE IF NOT EXISTS routes (key TEXT PRIMARY KEY, sha TEXT, version TEXT, data BLOB)')
        for i,p in enumerate(photos):
            identity=feature_identity(model,p)
            if cancelled():return None
            row=None if force else con.execute('SELECT sha,version,data FROM routes WHERE key=?',(p['key'],)).fetchone()
            if row and row[:2]==(p['sha256'],identity):scores=np.frombuffer(row[2],np.float32).reshape(-1,5)
            else:
                scores=routing_scores(subject.frames(p,thumbs))
                con.execute('INSERT OR REPLACE INTO routes VALUES (?,?,?,?)',(p['key'],p['sha256'],identity,scores.tobytes()))
            result.append(eligible(scores))
            if i%32==0:con.commit()
            if progress:progress(i+1,len(photos),'subject_routing')
    return result


def character_threshold(threshold):
    # One user strictness control; model scores have distinct scales.
    return float(np.interp(threshold,[.65,.72,.80],[.78,character.DEFAULT_THRESHOLD,.85]))


def choose_match(general,extra,threshold):
    choices=[]
    for value,cut in ((general,threshold),(extra,character_threshold(threshold))):
        if value is not None and value[0]>=cut:
            choices.append(((value[0]-cut)/max(1-cut,1e-6),value))
    return max(choices,key=lambda x:x[0])[1] if choices else None


def general_scores(a,b,threshold):
    """Require support from three distinct region pairs, not one maximum.

    Cached descriptors 2:6 are four overlapping spatial windows. Descriptor 1
    is the entire patch average and cannot count as an independent region.
    This is a conservative visual check, NOT a detector or identity guarantee.
    """
    whole=a[:,0]@b[:,0].T
    regions=np.einsum('frd,gsd->fgrs',a[:,2:6],b[:,2:6])
    # Enumerate only 24 assignments of four regions. One target region cannot
    # support all source regions; allow one unmatched/occluded region.
    assigned=regions[:,:,np.arange(4)[None,:],_REGION_ASSIGNMENTS]
    supported=(assigned>=threshold).sum(axis=-1)>=3
    local=np.max(np.where(supported,assigned.mean(axis=-1),-1),axis=-1)
    return np.where((whole>=.45)&(local>=0),.4*whole+.6*local,-1)


def verify_pair(a,b,gate_a,gate_b,char_a,char_b,threshold,perceptual_a=None,perceptual_b=None,*,regroup=False,general_allowed=None):
    """Frame-pair routing with explicit abstention on inconsistent routes.

    A rejected or unavailable identity comparison cannot fall back to style.
    Search *all* eligible frame pairs, not just the old global maximum.
    """
    scores=general_scores(a,b,threshold)
    scores=np.where(~gate_a[:,None]&~gate_b[None,:],scores,-1)
    if general_allowed is not None:
        if general_allowed.shape!=scores.shape:raise ValueError('Incompatible sampled frame caches')
        scores=np.where(general_allowed,scores,-1)
    support=None
    if perceptual_a is not None or perceptual_b is not None:
        if perceptual_a is None or perceptual_b is None:raise ValueError('Missing perceptual evidence')
        if len(perceptual_a)!=len(a) or len(perceptual_b)!=len(b):raise ValueError('Incompatible sampled frame caches')
        # Development presets, not identity probabilities. Same frame pair must
        # supply every signal; never combine evidence from unrelated scenes.
        perception=perceptual_a@perceptual_b.T
        support=perception>=float(np.interp(threshold,[.65,.72,.80],[.5,.6,.7]))
        scores=np.where(support,scores,-1)
    af,bf=np.unravel_index(int(scores.argmax()),scores.shape)
    g=(float(scores[af,bf]),int(af),int(bf))
    e=None
    if char_a is not None and char_b is not None and gate_a.any() and gate_b.any():
        if support is None:
            score,af,bf=character.similarity(char_a[gate_a],char_b[gate_b])
            e=(score,int(np.flatnonzero(gate_a)[af]),int(np.flatnonzero(gate_b)[bf]))
        else:
            values=np.clip((1+char_a@char_b.T)/2,0,1)
            cut=float(np.interp(threshold,[.65,.72,.80],[character.DEFAULT_THRESHOLD,.85,.88]))
            # Stronger identity evidence may tolerate a larger appearance change.
            # Keep both signals on the very same frame pair; routing disagreement
            # still abstains. These presets are development-calibrated, not probabilities.
            strong=float(np.interp(threshold,[.65,.72,.80],[.85,.87,.91]))
            floor=float(np.interp(threshold,[.65,.72,.80],[.45,.50,.60]))
            accepted=support&(values>=cut)
            if regroup:accepted|=(perception>=floor)&(values>=strong)
            values=np.where(gate_a[:,None]&gate_b[None,:]&accepted,values,-1)
            af,bf=np.unravel_index(int(values.argmax()),values.shape)
            e=(float(values[af,bf]),int(af),int(bf))
    chosen=choose_match(g,e,threshold)
    if chosen is None:return None
    route='regions' if chosen is g else 'identity'
    cut=threshold if route=='regions' else character_threshold(threshold)
    margin=(chosen[0]-cut)/max(1-cut,1e-6)
    return margin,chosen,route


def cluster(photos,thumbs,scope='all',threshold=.72,progress=None,cancelled=lambda:False,force=False):
    from .vision import quality
    from .acceleration import cpu_budget
    # MediaStore/directory enumeration order is not recognition evidence. Keep
    # reference and bounded-candidate choices stable when quality is tied.
    ordered=sorted(photos,key=lambda p:(*quality(p),p['sha256'],p['key']),reverse=True)
    with cpu_budget(), (closing(perceptual.VectorCache(thumbs,cancelled,force)) if perceptual.installed() else nullcontext()) as verifier, \
            (closing(complementary.VectorCache(thumbs,cancelled,force)) if complementary.installed() else nullcontext()) as supplement, \
            (closing(identity_refine.VectorCache(thumbs,cancelled,force)) if complementary.installed() and identity_refine.installed() else nullcontext()) as identity_verifier, \
            (closing(domain_refine.VectorCache(thumbs,cancelled,force)) if identity_verifier is not None and domain_refine.installed() else nullcontext()) as domain_verifier, \
            (closing(local_context.VectorCache(thumbs,cancelled,force)) if domain_verifier is not None and local_context.installed() else nullcontext()) as local_verifier, \
            (closing(identity_extra.VectorCache(thumbs,cancelled,force)) if local_verifier is not None and identity_extra.installed() else nullcontext()) as extra_verifier:
        general=subject.vectors(ordered,thumbs,progress,cancelled,force)
        if general is None:return None
        gates=load_routes(ordered,thumbs,progress,cancelled,force)
        if gates is None:return None
        if domain_verifier is not None:
            for i,gate in enumerate(gates):
                if cancelled():return None
                if not gate.any():continue
                domain=domain_verifier.get(ordered[i])
                if domain is None:return None
                gates[i]=domain_refine.exclude_confident_real(gate,domain)
                if progress:progress(i+1,len(ordered),'subject_routing')
        selected=[i for i,mask in enumerate(gates) if mask.any()]
        def report(done,total,phase):
            if progress:progress(done,total,'subject_supplement')
        extra=character.vectors([ordered[i] for i in selected],thumbs,report,cancelled,force) if selected else []
        if extra is None:return None
        characters=dict(zip(selected,extra))
        for i in selected:
            if len(characters[i])!=len(gates[i]):raise ValueError('Incompatible sampled frame caches')
        def ensure_characters(r,i):
            missing=[j for j in (r,i) if j not in characters]
            if missing:
                values=character.vectors([ordered[j] for j in missing],thumbs,None,cancelled,force)
                if values is None:raise subject_merge.Cancelled()
                characters.update(zip(missing,values))

        @lru_cache(maxsize=8192)
        def general_permission(r,i):
            if domain_verifier is None:return None
            mask=~gates[r][:,None]&~gates[i][None,:]
            if not mask.any():return None
            da=domain_verifier.get(ordered[r]);db=domain_verifier.get(ordered[i])
            if da is None or db is None:raise subject_merge.Cancelled()
            mask &= (da[:,0,None]>=.95)&(db[None,:,0]>=.95)
            if not mask.any():return None
            ensure_characters(r,i)
            mask &= (1+characters[r]@characters[i].T)/2<.75
            if not mask.any():return None
            ia=identity_verifier.get(ordered[r]);ib=identity_verifier.get(ordered[i])
            if ia is None or ib is None:raise subject_merge.Cancelled()
            # Negative evidence only affects the general comparison on this
            # exact frame pair; specialist/local routes still need their own proof.
            return ~(mask&((1+ia@ib.T)/2<.75))
        gm=np.empty((sum(len(v) for v in general),6,subject.DIM),np.float32)
        go=np.empty(len(gm),np.int32);gu=0
        cm=np.empty((sum(int(gates[i].sum()) for i in selected),character.DIM),np.float32)
        co=np.empty(len(cm),np.int32);cu=0
        reps=[];groups=[];exact={};proposals=[];ct=character_threshold(threshold)
        for i,(p,v) in enumerate(zip(ordered,general)):
            if cancelled():return None
            identity=(p['sha256'],p['album'] if scope=='album' else '')
            if identity in exact:
                groups[exact[identity]].append(dict(p,score=1.,reason='文件完全相同',relation='exact'))
            else:
                candidates=set();best=None;suggestions=[]
                for offset in range(0,gu,512):
                    block=gm[offset:min(gu,offset+512)]
                    whole=v[:,0]@block[:,0].T
                    local=(v[:,1:].reshape(-1,subject.DIM)@block[:,1:].reshape(-1,subject.DIM).T).reshape(len(v),5,len(block),5).max(axis=(1,3))
                    scores=np.max(np.where(whole>=.45,.4*whole+.6*local,-1),axis=0)
                    candidates.update(go[offset:offset+len(block)][scores>=threshold-1e-6].tolist())
                cv=characters[i][gates[i]] if i in characters and gates[i].any() else None
                if cv is not None:
                    for offset in range(0,cu,4096):
                        scores=np.max((1+cv@cm[offset:min(cu,offset+4096)].T)/2,axis=0)
                        candidates.update(co[offset:offset+len(scores)][scores>=ct-1e-6].tolist())
                for j in sorted(candidates):
                    r=reps[j]
                    if scope=='album' and p['album']!=ordered[r]['album']:continue
                    match=verify_pair(general[r],v,gates[r],gates[i],characters.get(r),characters.get(i),threshold)
                    if match and match[2]=='regions':
                        try:allowed=general_permission(r,i)
                        except subject_merge.Cancelled:return None
                        if allowed is not None:
                            match=verify_pair(general[r],v,gates[r],gates[i],characters.get(r),characters.get(i),threshold,general_allowed=allowed)
                    if match:
                        heapq.heappush(suggestions,(match[0],j))
                        if len(suggestions)>4:heapq.heappop(suggestions)
                    if match and verifier is not None:
                        if progress:progress(i,len(ordered),'subject_match')
                        pa=verifier.get(ordered[r]);pb=verifier.get(p)
                        if pa is None or pb is None:return None
                        match=verify_pair(general[r],v,gates[r],gates[i],characters.get(r),characters.get(i),threshold,pa,pb)
                        if match and match[2]=='regions':
                            try:allowed=general_permission(r,i)
                            except subject_merge.Cancelled:return None
                            if allowed is not None:
                                match=verify_pair(general[r],v,gates[r],gates[i],characters.get(r),characters.get(i),threshold,pa,pb,general_allowed=allowed)
                    if match:
                        margin,chosen,route=match
                        if best is None or margin>best[0]:best=(margin,j,chosen,route)
                if best:
                    _,j,(score,af,bf),route=best
                    reason=('多个不同区域相近，仍需确认是否同一主体' if route=='regions' else '身份模型特征相近，仍需人工确认')
                    if verifier is not None:reason='多模型候选核验通过，仍需人工确认主体'
                    groups[j].append(dict(p,score=round(min(score,.999),4),relation='subject',reason=reason,reference_frame=af,match_frame=bf))
                else:
                    j=len(groups);groups.append([dict(p,score=1.,reason='主体组参考',relation='reference')]);reps.append(i)
                    gm[gu:gu+len(v)]=v;go[gu:gu+len(v)]=j;gu+=len(v)
                    if cv is not None:cm[cu:cu+len(cv)]=cv;co[cu:cu+len(cv)]=j;cu+=len(cv)
                    exact[identity]=j
                proposals.extend((j,other,i,margin) for margin,other in suggestions if other!=j)
            if progress:progress(i+1,len(ordered),'subject_match')
        indices={p['key']:i for i,p in enumerate(ordered)}
        initial=[[indices[p['key']] for p in group] for group in groups]
        originals={tuple(ids):group for ids,group in zip(initial,groups)}

        use_supplement=False
        def verify_reference(r,i):
            if cancelled():raise subject_merge.Cancelled()
            a,b=ordered[r],ordered[i]
            if scope=='album' and a['album']!=b['album']:return None
            if a['sha256']==b['sha256']:return (1.,(1.,0,0),'exact')
            args=(general[r],general[i],gates[r],gates[i],characters.get(r),characters.get(i),threshold)
            match=verify_pair(*args)
            if verifier is not None and (match or use_supplement):
                pa=verifier.get(a);pb=verifier.get(b)
                if pa is None or pb is None:raise subject_merge.Cancelled()
                if match:match=verify_pair(*args,pa,pb,regroup=True)
                if match and match[2]=='regions':
                    allowed=general_permission(r,i)
                    if allowed is not None:match=verify_pair(*args,pa,pb,regroup=True,general_allowed=allowed)
                if match is None and use_supplement:
                    sa=supplement.get(a);sb=supplement.get(b)
                    if sa is None or sb is None:raise subject_merge.Cancelled()
                    match=complementary.verify(general[r],general[i],gates[r],gates[i],characters.get(r),characters.get(i),pa,pb,sa,sb,threshold)
                    if match:
                        af,bf=match[1][1:]
                        if not gates[r][af] and not gates[i][bf]:
                            allowed=general_permission(r,i)
                            if allowed is not None:
                                match=complementary.verify(general[r],general[i],gates[r],gates[i],characters.get(r),characters.get(i),pa,pb,sa,sb,threshold,general_allowed=allowed)
                    if match is None and extra_verifier is not None:
                        da=domain_verifier.get(a);db=domain_verifier.get(b)
                        if da is None or db is None:raise subject_merge.Cancelled()
                        mask=identity_refine.candidate_mask(da[:,0]>=.95,db[:,0]>=.95,pa,pb,sa,sb,threshold)
                        if mask.any():
                            ensure_characters(r,i)
                            mask=identity_extra.candidate_mask(da,db,characters[r],characters[i],pa,pb,sa,sb,threshold)
                            if mask.any():
                                ia=identity_verifier.get(a);ib=identity_verifier.get(b)
                                if ia is None or ib is None:raise subject_merge.Cancelled()
                                mask=identity_extra.large_mask(mask,ia,ib,threshold)
                                if mask.any():
                                    if progress:progress(i,len(ordered),'subject_extra_identity')
                                    xa=extra_verifier.get(a);xb=extra_verifier.get(b)
                                    if cancelled():raise subject_merge.Cancelled()
                                    if xa is not None and xb is not None:match=identity_extra.verify(mask,xa,xb,ia,ib,threshold)
                    if match is None and identity_verifier is not None:
                        mask=identity_refine.candidate_mask(gates[r],gates[i],pa,pb,sa,sb,threshold)
                        if mask.any():
                            ia=identity_verifier.get(a);ib=identity_verifier.get(b)
                            if ia is None or ib is None:raise subject_merge.Cancelled()
                            match=identity_refine.verify(mask,ia,ib,threshold)
                    if match is None and domain_verifier is not None:
                        mask=domain_refine.candidate_mask(gates[r],gates[i],pa,pb,sa,sb,threshold)
                        if mask.any():
                            da=domain_verifier.get(a);db=domain_verifier.get(b)
                            if da is None or db is None:raise subject_merge.Cancelled()
                            mask=domain_refine.routed_mask(mask,da,db)
                            if mask.any():
                                ensure_characters(r,i)
                                mask=domain_refine.identity_mask(mask,characters[r],characters[i],threshold)
                                if mask.any():
                                    ia=identity_verifier.get(a);ib=identity_verifier.get(b)
                                    if ia is None or ib is None:raise subject_merge.Cancelled()
                                    match=identity_refine.verify(mask,ia,ib,threshold)
                    if match is None and local_verifier is not None and (sa@sb.T>=.8).any():
                        da=domain_verifier.get(a);db=domain_verifier.get(b)
                        if da is None or db is None:raise subject_merge.Cancelled()
                        if (da[:,0]>=.9).any() and (db[:,0]>=.9).any():
                            ensure_characters(r,i)
                            mask=local_context.whole_mask(da,db,characters[r],characters[i],sa,sb)
                            if mask.any():
                                if progress:progress(i,len(ordered),'subject_local_context')
                                la=local_verifier.get(a);lb=local_verifier.get(b)
                                if la is not None or lb is not None:
                                    def whole_large(photo):
                                        value=identity_verifier.get(photo)
                                        if value is None:raise subject_merge.Cancelled()
                                        return value
                                    wa=dict(small=characters[r],load_large=lambda:whole_large(a),semantic=sa,perception=pa)
                                    wb=dict(small=characters[i],load_large=lambda:whole_large(b),semantic=sb,perception=pb)
                                    match=local_context.verify(mask,la,lb,wa,wb,threshold,
                                        lambda:local_verifier.large(a),lambda:local_verifier.large(b))
            return match

        try:
            merged=subject_merge.consolidate(initial,proposals,verify_reference,cancelled,progress)
            if supplement is not None:
                extra_proposals=complementary.proposals(merged,ordered,supplement,scope,cancelled,progress)
                if local_verifier is not None:
                    extra_proposals+=local_context.proposals(merged,ordered,characters,gates,scope,cancelled,progress)
                use_supplement=True
                merged=subject_merge.consolidate(merged,extra_proposals,verify_reference,cancelled,progress,True)
                if local_verifier is not None:
                    merged=subject_singletons.recover(merged,ordered,characters,verify_reference,scope,cancelled,progress)
            final=[]
            for ids in merged:
                if cancelled():return None
                if len(ids)<2:continue
                if tuple(ids) in originals:
                    final.append(originals[tuple(ids)]);continue
                r=ids[0]
                group=[dict(ordered[r],score=1.,reason='主体组参考',relation='reference')]
                for i in ids[1:]:
                    match=verify_reference(r,i)
                    if match is None:raise ValueError('Subject reference verification changed')
                    _,(score,af,bf),route=match
                    if route=='exact':
                        group.append(dict(ordered[i],score=1.,reason='文件完全相同',relation='exact'))
                    else:
                        reason=('多个不同区域相近，仍需确认是否同一主体' if route=='regions' else '身份模型特征相近，仍需人工确认')
                        if verifier is not None:reason='多模型候选核验通过，仍需人工确认主体'
                        group.append(dict(ordered[i],score=round(min(score,.999),4),relation='subject',reason=reason,reference_frame=af,match_frame=bf))
                        if isinstance(route,dict):group[-1]['subject_evidence']=route
                final.append(group)
            return sorted(final,key=len,reverse=True)
        except subject_merge.Cancelled:
            return None
