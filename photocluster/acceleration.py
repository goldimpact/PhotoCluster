"""Optional local CUDA math with explicit CPU fallback. No network access."""
import os
import threading
from functools import lru_cache

import cv2
import numpy as np
from threadpoolctl import threadpool_limits
import psutil

_lock=threading.RLock()
_state={'backend':'cpu','device':None,'reason':'尚未探测 CUDA','batches':0,'pairs':0}


def workers():
    value=os.environ.get('PHOTOCLUSTER_CPU_WORKERS')
    return max(1,min(32,int(value))) if value else min(8,psutil.cpu_count(logical=False) or 4)


def cpu_budget():
    # Parallel image tasks each use one BLAS thread; avoid 8 x 16 contention.
    return threadpool_limits(limits=1,user_api='blas')


def hardware_info():
    return dict(cpu_physical=psutil.cpu_count(logical=False),cpu_logical=os.cpu_count(),
                memory_gb=round(psutil.virtual_memory().total/1024**3),workers=workers(),
                accelerator=status(),model_inference='CPU · INT8',
                sift='CUDA 批量特征匹配 + CPU 几何验证' if _state['backend']=='cuda' and os.environ.get('PHOTOCLUSTER_GEOMETRY_GPU','1')=='1' else 'CPU 并行')


@lru_cache(maxsize=1)
def cuda():
    if os.environ.get('PHOTOCLUSTER_ACCELERATOR','auto').lower()=='cpu':
        _state['reason']='配置为 CPU'
        return None
    try:
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount()<1:raise RuntimeError('未找到 CUDA 设备')
        with cp.cuda.Device(0):
            cp.cuda.cublas.setMathMode(cp.cuda.device.get_cublas_handle(), 2)  # pedantic FP32, no TF32
            x=cp.ones((32,32),dtype=cp.float32)
            if float((x@x)[0,0])!=32:raise RuntimeError('CUDA 自检失败')
        name=cp.cuda.runtime.getDeviceProperties(0)['name'].decode()
        _state.update(backend='cuda',device=name,reason=None)
        return cp
    except Exception as exc:
        _state.update(backend='cpu',reason=str(exc))
        return None


def status():
    return dict(_state)


def fallback(reason):
    _state.update(backend='cpu',reason=reason)


def descriptor_batch(pairs):
    """Exact SIFT ratio matches; bounded GPU batches, no approximate search."""
    if not pairs:return []
    cp=cuda()
    if cp is None:return None
    results=[]
    try:
        with _lock,cp.cuda.Device(0):
            # Thread-local handles must also disable reduced precision.
            cp.cuda.cublas.setMathMode(cp.cuda.device.get_cublas_handle(),2)
            for start in range(0,len(pairs),16):
                chunk=pairs[start:start+16]
                na=max(len(a) for a,b in chunk);nb=max(len(b) for a,b in chunk)
                aa=np.zeros((len(chunk),na,128),np.float32);bb=np.zeros((len(chunk),nb,128),np.float32)
                lengths=[]
                for k,(a,b) in enumerate(chunk):
                    aa[k,:len(a)]=a;bb[k,:len(b)]=b;lengths.append(len(b))
                a=cp.asarray(aa);b=cp.asarray(bb)
                distances=-2*(a@b.transpose(0,2,1))
                distances+=cp.sum(a*a,axis=2)[:,:,None]
                distances+=cp.sum(b*b,axis=2)[:,None,:]
                distances=cp.where(cp.arange(nb)[None,None,:]<cp.asarray(lengths)[:,None,None],distances,cp.inf)
                nearest=distances.argmin(axis=2)
                batches=cp.arange(len(chunk))[:,None];rows=cp.arange(na)[None,:]
                first=distances[batches,rows,nearest].copy()
                distances[batches,rows,nearest]=cp.inf
                second=distances.min(axis=2)
                accepted=first<(.72**2)*second
                host=cp.asnumpy(cp.stack((nearest,first,accepted),axis=2))
                for k,(a,b) in enumerate(chunk):
                    results.append([cv2.DMatch(int(i),int(host[k,i,0]),float(host[k,i,1]))
                                    for i in np.flatnonzero(host[k,:len(a),2])])
                _state['batches']+=1;_state['pairs']+=len(chunk)
        return results
    except Exception as exc:
        _state.update(backend='cpu',reason='CUDA 批量匹配失败，已回退：'+str(exc))
        return None


class FrameSearch:
    """GPU block retrieval over immutable frame vectors. Representatives stay CPU-owned."""
    def __init__(self,vectors):
        self.cp=cuda()
        if self.cp is None:raise RuntimeError('CUDA unavailable')
        self.offsets=np.cumsum([0]+[len(v) for v in vectors])
        self.owners=np.repeat(np.arange(len(vectors)),[len(v) for v in vectors])
        self.flat=np.concatenate(vectors)
        self.device=self.cp.asarray(self.flat)
        self.start=self.end=0;self.scores=None

    def candidates(self,index,active,threshold):
        cp=self.cp
        if not self.start<=index<self.end:
            self.start=index;self.end=min(index+64,len(self.offsets)-1)
            while self.end>index+1 and (self.offsets[self.end]-self.offsets[index])*self.offsets[self.end]*4>64*1024**2:
                self.end=index+(self.end-index)//2
            with _lock,cp.cuda.Device(0):
                cp.cuda.cublas.setMathMode(cp.cuda.device.get_cublas_handle(),2)
                block=self.device[self.offsets[index]:self.offsets[self.end]]@self.device[:self.offsets[self.end]].T
                self.scores=cp.asnumpy(block)
                _state['batches']+=1
        begin=self.offsets[index]-self.offsets[self.start]
        end=self.offsets[index+1]-self.offsets[self.start]
        scores=np.max(self.scores[begin:end,:self.offsets[index]],axis=0)
        # All candidates get the original CPU score. Margin includes float-roundoff.
        photos=np.unique(self.owners[:len(scores)][scores>=threshold-1e-5])
        return sorted(active[int(p)] for p in photos if int(p) in active)
