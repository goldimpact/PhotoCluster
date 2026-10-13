"""Optional local context review; detections propose views, never identities.

Every crop retains its original frame and pixel box. General recognition remains
available to all media. This specialist cannot identify arbitrary real objects.
"""
from collections import OrderedDict
import io
import math
from pathlib import Path
import sqlite3
import threading

import numpy as np

from .config import DATA
from . import character, perceptual, complementary, identity_refine, domain_refine, subject_merge

MODEL=DATA/'models/subject-local-context.onnx'
VERSION='face-v14n-dynamic1216-single035-context24-middle-v1'
MAX_NEW_MEDIA=512
MAX_RETRIEVAL_FRAMES=16384
_session=None
_identity=None
_lock=threading.Lock()


def installed():
    return MODEL.is_file() and complementary.installed() and identity_refine.installed() and domain_refine.installed()


def model_identity():
    from .semantic import file_identity
    return ':'.join((VERSION,file_identity(MODEL),character.model_identity(),perceptual.model_identity(),
                     complementary.model_identity(),identity_refine.model_identity()))


def session():
    global _session,_identity
    from .semantic import file_identity
    identity=VERSION+':'+file_identity(MODEL)
    with _lock:
        if _session is None or _identity!=identity:
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            _session=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _identity=identity
    return _session


def context(image,cancelled=lambda:False):
    if cancelled():raise subject_merge.Cancelled()
    image=image.convert('RGB');w,h=image.size
    ratio=min(1,1216/w,1216/h);nw,nh=math.ceil(w*ratio/32)*32,math.ceil(h*ratio/32)*32
    # Upstream dynamic RGB preprocessing resizes to multiples of 32, no letterbox.
    batch=np.asarray(image.resize((nw,nh)),np.float32).transpose(2,0,1)[None]/255
    raw=np.asarray(session().run(['output0'],{'images':batch})[0],np.float32)
    if raw.ndim!=3 or raw.shape[0]!=1 or raw.shape[1]!=5 or not np.isfinite(raw).all():
        raise ValueError('Invalid local context detector output')
    rows=raw[0,:,raw[0,4]>.35]
    kept=[]
    for row in rows[np.argsort(-rows[:,4],kind='stable')]:
        if cancelled():raise subject_merge.Cancelled()
        cx,cy,bw,bh,score=row
        if bw<=0 or bh<=0:continue
        box=np.array([cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2],float)
        duplicate=False
        for old in kept:
            overlap=np.maximum(0,np.minimum(box[2:],old[2:])-np.maximum(box[:2],old[:2])).prod()
            union=(box[2:]-box[:2]).prod()+(old[2:]-old[:2]).prod()-overlap
            if overlap/max(union,1e-8)>.7:duplicate=True;break
        if not duplicate:
            kept.append(box)
            if len(kept)>1:return None  # Do not choose a character in a crowded frame.
    if not kept:return None
    box=kept[0]*np.array([w/nw,h/nh,w/nw,h/nh]);cx,cy=(box[:2]+box[2:])/2
    side=max(box[2:]-box[:2])*2.4
    box=(max(0,int(cx-side*.5)),max(0,int(cy-side*.55)),min(w,int(cx+side*.5)),min(h,int(cy+side*.45)))
    if min(box[2]-box[0],box[3]-box[1])<32:return None
    return image.crop(box),box


class VectorCache:
    """Separate versioned cache including no-detection results; bounded cold work."""
    def __init__(self,thumbs,cancelled=lambda:False,force=False):
        self.thumbs=Path(thumbs);self.cancelled=cancelled;self.force=force
        self.identity=model_identity();self.memory=OrderedDict();self.refreshed=set();self.new=0;self.pending=0
        self.large_new=0
        self.con=sqlite3.connect(self.thumbs/'subject-local-context.sqlite3',timeout=30)
        self.con.execute('CREATE TABLE IF NOT EXISTS contexts (key TEXT PRIMARY KEY, sha TEXT, version TEXT, data BLOB)')

    def get(self,photo):
        from .frame_policy import feature_identity
        from .subject import frames
        if self.cancelled():raise subject_merge.Cancelled()
        version=feature_identity(self.identity,photo);key=(photo['key'],photo['sha256'],version)
        if key in self.memory:
            self.memory.move_to_end(key);return self.memory[key]
        row=None if self.force and key not in self.refreshed else self.con.execute(
            'SELECT sha,version,data FROM contexts WHERE key=?',(key[0],)).fetchone()
        if row and row[:2]==key[1:]:
            if not row[2]:value=None
            else:
                with np.load(io.BytesIO(row[2]),allow_pickle=False) as data:
                    value={name:data[name] for name in data.files}
                value['frame']=int(value['frame']);value['box']=tuple(map(int,value['box']))
        else:
            # Read existing cached decisions even after this job's cold-work cap.
            if self.new>=MAX_NEW_MEDIA:return None
            self.new+=1;images=frames(photo,self.thumbs);frame=len(images)//2
            view=context(images[frame],self.cancelled);value=None
            if view is not None:
                image,box=view;value=dict(frame=frame,box=box)
                for name,encoder in (('small',character.encode),('perception',perceptual.encode),
                                     ('semantic',complementary.encode)):
                    if self.cancelled():raise subject_merge.Cancelled()
                    encoded=encoder([image])
                    if encoded is None:raise subject_merge.Cancelled()
                    value[name]=encoded
            if self.cancelled():raise subject_merge.Cancelled()
            blob=b''
            if value is not None:
                buffer=io.BytesIO();np.savez(buffer,**value);blob=buffer.getvalue()
            self.con.execute('INSERT OR REPLACE INTO contexts VALUES (?,?,?,?)',(*key,blob))
            if self.force:self.refreshed.add(key)
            self.pending+=1
            if self.pending>=16:self.con.commit();self.pending=0
        self.memory[key]=value
        if len(self.memory)>64:self.memory.popitem(last=False)
        return value

    def large(self,photo):
        """Finish an existing crop only after cheaper same-frame evidence passes.

        Old complete v11 records are reused as-is. Partial records contain real
        computed features, never a placeholder negative identity verdict.
        """
        from .frame_policy import feature_identity
        from .subject import frames
        value=self.get(photo)
        if value is None:return None
        if 'large' in value:return value['large']
        if self.large_new>=MAX_NEW_MEDIA:return None
        self.large_new+=1
        images=frames(photo,self.thumbs)
        encoded=identity_refine.encode([images[value['frame']].crop(value['box'])],self.cancelled)
        if encoded is None or self.cancelled():raise subject_merge.Cancelled()
        value['large']=encoded
        buffer=io.BytesIO();np.savez(buffer,**value)
        version=feature_identity(self.identity,photo)
        self.con.execute('UPDATE contexts SET data=? WHERE key=? AND sha=? AND version=?',
                         (buffer.getvalue(),photo['key'],photo['sha256'],version))
        self.pending+=1
        if self.pending>=16:self.con.commit();self.pending=0
        return encoded

    def close(self):
        try:self.con.commit()
        finally:self.con.close()


def whole_mask(da,db,ca,cb,sa,sb):
    if len(da)!=len(ca) or len(da)!=len(sa) or len(db)!=len(cb) or len(db)!=len(sb):
        raise ValueError('Incompatible sampled frame caches')
    return (da[:,0,None]>=.9)&(db[None,:,0]>=.9)&(sa@sb.T>=.8)&((1+ca@cb.T)/2>=.75)


def verify(mask,a,b,whole_a,whole_b,threshold,large_a=None,large_b=None):
    """Crop/crop then crop/whole; all signals align with one original frame pair."""
    def view(local,whole):
        if local is None:return None
        f=local['frame']
        if not 0<=f<len(whole['small']):raise ValueError('Incompatible sampled frame caches')
        return dict(local,frames=np.array([f]))
    aa,bb=view(a,whole_a),view(b,whole_b)
    if aa is not None:aa['load_large']=large_a
    if bb is not None:bb['load_large']=large_b
    wa=dict(whole_a,frames=np.arange(len(whole_a['small'])),box=None)
    wb=dict(whole_b,frames=np.arange(len(whole_b['small'])),box=None)
    for left,right in ((aa,bb),(aa,wb),(wa,bb)):
        if left is None or right is None:continue
        selected=mask[np.ix_(left['frames'],right['frames'])]
        if not selected.any():continue
        ones_a=np.ones(len(left['frames']),bool);ones_b=np.ones(len(right['frames']),bool)
        selected &= identity_refine.candidate_mask(ones_a,ones_b,left['perception'],right['perception'],left['semantic'],right['semantic'],threshold)
        selected=domain_refine.identity_mask(selected,left['small'],right['small'],threshold)
        if not selected.any():continue
        def large(value):
            if 'large' not in value:
                if value.get('load_large') is None:raise ValueError('Missing local identity evidence')
                encoded=value['load_large']()
                if encoded is not None:value['large']=encoded
                return encoded
            return value['large']
        ia=large(left);ib=large(right)
        if ia is None or ib is None:continue  # Cold-work budget, not an identity verdict.
        found=identity_refine.verify(selected,ia,ib,threshold)
        if found:
            margin,(score,af,bf),_=found
            provenance=dict(kind='local_context',reference_box=left['box'],match_box=right['box'])
            return margin,(score,int(left['frames'][af]),int(right['frames'][bf])),provenance
    return None


def proposals(groups,photos,characters,gates,scope,cancelled,progress=None):
    """Reuse existing identity vectors; no detector or new media extraction here."""
    def entries(group):
        for i in group:
            if i in characters:
                for vector in characters[i][gates[i]]:yield i,vector
    streams=[(j,iter(entries(g))) for j,g in enumerate(groups) if len(g)>=2]
    samples=[];vectors=[]
    # Round robin avoids exhausting the budget in the first large group.
    while streams and len(vectors)<MAX_RETRIEVAL_FRAMES:
        remaining=[]
        for owner,stream in streams:
            if cancelled():raise subject_merge.Cancelled()
            try:i,vector=next(stream)
            except StopIteration:continue
            samples.append((owner,i));vectors.append(vector);remaining.append((owner,stream))
            if len(vectors)>=MAX_RETRIEVAL_FRAMES:break
        streams=remaining
    if not vectors:return []
    matrix=np.stack(vectors);result=[]
    for start in range(0,len(matrix),64):
        best=[{} for _ in matrix[start:start+64]]
        for offset in range(0,len(matrix),2048):
            if cancelled():raise subject_merge.Cancelled()
            scores=(1+matrix[start:start+64]@matrix[offset:offset+2048].T)/2
            for row,values in enumerate(scores):
                owner,i=samples[start+row]
                for at in np.flatnonzero(values>=.82):
                    other,_=samples[offset+at]
                    if owner==other:continue
                    if scope=='album' and photos[i]['album']!=photos[groups[other][0]]['album']:continue
                    best[row][other]=max(best[row].get(other,0),float(values[at]))
        for row,neighbors in enumerate(best):
            owner,i=samples[start+row]
            result.extend((owner,other,i,score) for other,score in sorted(neighbors.items(),key=lambda x:(-x[1],x[0]))[:4])
        if progress:progress(min(start+64,len(matrix)),len(matrix),'subject_local_retrieval')
    return result
