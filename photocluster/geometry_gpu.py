"""One GEMM per descriptor block, fused exact nearest-neighbour reduction.

Unlike padded pair batches, each source descriptor and each target descriptor
is transferred only once per candidate set. CPU still verifies all geometry.
"""
import numpy as np
import cv2
from .acceleration import cuda, fallback, _lock, _state

_kernel=None
SOURCE=r'''
extern "C" __global__ void nearest(
    const float* dots, const float* an, const float* bn, const int* offsets,
    int rows, int columns, int frames, int* out_index, float* out_distance) {
    int lane=threadIdx.x&31;
    int row=blockIdx.x*4+(threadIdx.x>>5);
    int frame=blockIdx.y;
    if(row>=rows)return;
    int start=offsets[frame],end=offsets[frame+1];
    float first=1.0e30f,second=1.0e30f;int index=2147483647;
    for(int j=start+lane;j<end;j+=32){
        float d=(an[row]+bn[j])-2.0f*dots[row*columns+j];
        if(d<first || (d==first && j<index)){second=first;first=d;index=j;}
        else if(d<second)second=d;
    }
    float best=first;int best_index=index;
    for(int stride=16;stride;stride>>=1){
        float other=__shfl_down_sync(0xffffffff,best,stride);
        int oi=__shfl_down_sync(0xffffffff,best_index,stride);
        if(other<best || (other==best && oi<best_index)){best=other;best_index=oi;}
    }
    best=__shfl_sync(0xffffffff,best,0);
    best_index=__shfl_sync(0xffffffff,best_index,0);
    float runner=index==best_index?second:first;
    for(int stride=16;stride;stride>>=1)
        runner=fminf(runner,__shfl_down_sync(0xffffffff,runner,stride));
    if(lane==0){
        int at=frame*rows+row;
        out_index[at]=(end-start>=2 && best<0.5184f*runner)?best_index-start:-1;
        out_distance[at]=best;
    }
}
'''


def match_sources(sources,target,mirror=True):
    """Return per-source frame/flip maps, including empty rejected matches."""
    global _kernel
    cp=cuda()
    if cp is None:return None
    if len(sources)>64:
        results=[]
        for start in range(0,len(sources),64):
            part=match_sources(sources[start:start+64],target,mirror)
            if part is None:return None
            results.extend(part)
        return results
    maps=[{} for _ in sources];descriptors=[];owners=[]
    for n,source in enumerate(sources):
        for i in range(int(source['count'])):
            for flip in range(2 if mirror else 1):
                a=source[f'd{i}_{flip}']
                for j in range(int(target['count'])):maps[n][i,j,flip]=[]
                if len(a)>=14:
                    descriptors.append(a);owners.append((n,i,flip,len(a)))
    if not descriptors:return maps
    frames=[target[f'd{j}_0'] for j in range(int(target['count']))]
    offsets=np.cumsum([0]+[len(b) for b in frames]).astype(np.int32)
    if offsets[-1]<14:return maps
    try:
        with _lock,cp.cuda.Device(0):
            cp.cuda.cublas.setMathMode(cp.cuda.device.get_cublas_handle(),2)
            if _kernel is None:_kernel=cp.RawKernel(SOURCE,'nearest',options=('--fmad=false',))
            b=cp.asarray(np.concatenate(frames));bn=cp.sum(b*b,axis=1);off=cp.asarray(offsets)
            aa=np.concatenate(descriptors)
            indices=np.empty((len(frames),len(aa)),np.int32)
            distances=np.empty((len(frames),len(aa)),np.float32)
            for start in range(0,len(aa),32768):
                a=cp.asarray(aa[start:start+32768]);an=cp.sum(a*a,axis=1)
                dots=a@b.T;rows=len(a)
                ix=cp.empty((len(frames),rows),cp.int32);dd=cp.empty_like(ix,dtype=cp.float32)
                _kernel(((rows+3)//4,len(frames)),(128,),
                        (dots,an,bn,off,np.int32(rows),np.int32(len(b)),np.int32(len(frames)),ix,dd))
                indices[:,start:start+rows]=cp.asnumpy(ix)
                distances[:,start:start+rows]=cp.asnumpy(dd)
                _state['batches']+=1
            start=0
            for n,i,flip,count in owners:
                for j,bframe in enumerate(frames):
                    if len(bframe)<14:continue
                    ix=indices[j,start:start+count];dist=distances[j,start:start+count]
                    maps[n][i,j,flip]=[cv2.DMatch(int(r),int(ix[r]),float(dist[r])) for r in np.flatnonzero(ix>=0)]
                start+=count
            _state['pairs']+=len(owners)*len(frames)
        return maps
    except Exception as exc:
        fallback('CUDA 几何候选匹配失败，已回退 CPU：'+str(exc))
        return None
