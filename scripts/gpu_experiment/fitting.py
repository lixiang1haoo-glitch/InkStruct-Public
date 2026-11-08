"""Isolated FP64 fitting calculator; original filters/sort/collision remain CPU."""
import time
import numpy as np
from inkstruct.contextual_trajectory import anchors
from inkstruct.geometry import path_length

def cpu_fit(d,target,start_anchor=None):
    y=anchors([target]);ym=y.mean(axis=0)
    scale=np.sum(d['centered']*(y-ym),axis=(1,2))/np.maximum(d['denominator'],1e-300)
    offset=ym-scale[:,None]*d['mean']
    if start_anchor is not None:offset=np.asarray(start_anchor)-scale[:,None]*d['first']
    ratio=scale*d['length']/max(path_length(target),1e-9)
    first=scale[:,None]*d['first']+offset;last=scale[:,None]*d['last']+offset
    ends=np.maximum(np.linalg.norm(first-target[0],axis=1),np.linalg.norm(last-target[-1],axis=1))
    low=scale[:,None]*d['low']+offset;high=scale[:,None]*d['high']+offset
    scores=np.linalg.norm(scale[:,None,None]*d['x']+offset[:,None,:]-y,axis=2).mean(axis=1)+.01*(1-d['confidence'])
    return scale,offset,ratio,ends,low,high,scores

def packed_cpu(result):
    s,o,r,e,l,h,c=result
    return np.column_stack((s,o,r,e,l,h,c))

# One thread handles one real candidate/target pair; no float32/fast-math.
KERNEL=r'''
extern "C" __global__ void fit(const double* d,const double* q,double* out,int N,int Q){
 int id=blockDim.x*blockIdx.x+threadIdx.x;if(id>=N*Q)return;
 int n=id%N,b=id/N;const double* a=d+n*79;const double* y=q+b*42;
 double num=0;for(int k=0;k<32;k++)num+=a[32+k]*(y[k]-y[32+k%2]);
 double s=num/fmax(a[66],1e-300),ox=y[32]-s*a[64],oy=y[33]-s*a[65];
 if(y[41]>0){ox=y[38]-s*a[68];oy=y[39]-s*a[69];}
 double fx=s*a[68]+ox,fy=s*a[69]+oy,lx=s*a[70]+ox,ly=s*a[71]+oy;
 double dx=fx-y[34],dy=fy-y[35],ex=lx-y[36],ey=ly-y[37];
 double ends=fmax(sqrt(dx*dx+dy*dy),sqrt(ex*ex+ey*ey));
 double score=0;for(int k=0;k<16;k++){double x=s*a[2*k]+ox-y[2*k],z=s*a[2*k+1]+oy-y[2*k+1];score+=sqrt(x*x+z*z);}
 double* o=out+id*10;o[0]=s;o[1]=ox;o[2]=oy;o[3]=s*a[67]/fmax(y[40],1e-9);
 o[4]=ends;o[5]=s*a[72]+ox;o[6]=s*a[73]+oy;o[7]=s*a[74]+ox;o[8]=s*a[75]+oy;o[9]=score/16+.01*(1-a[76]);
}
'''
# q: anchors32, mean2, endpoints4, optional anchor2, length, anchor flag.

def pack_d(d):
    n=len(d['length'])
    return np.ascontiguousarray(np.column_stack((d['x'].reshape(n,32),d['centered'].reshape(n,32),d['mean'],d['denominator'],d['length'],d['first'],d['last'],d['low'],d['high'],d['confidence'],np.zeros((n,2)))))

def pack_q(target,start_anchor=None):
    y=anchors([target])
    return np.r_[y.ravel(),y.mean(axis=0),target[0],target[-1],start_anchor if start_anchor is not None else [0,0],path_length(target),int(start_anchor is not None)]

class GPUFit:
    def __init__(self):
        t=time.perf_counter()
        import cupy as cp
        self.cp=cp;cp.cuda.Device(0).use();cp.cuda.Device().synchronize()
        self.init_seconds=time.perf_counter()-t
        self.kernel=cp.RawKernel(KERNEL,'fit',options=('--fmad=false',))
        self.cache={};self.records=[];self.max_error=0;self.verified_pairs=0
    def upload(self,d):
        key=id(d)
        if key in self.cache and self.cache[key][0] is d:return self.cache[key][1],{'pack_s':0.,'h2d_s':0.}
        start=time.perf_counter();packed=pack_d(d);packing=time.perf_counter()-start
        start=time.perf_counter();dev=self.cp.asarray(packed);self.cp.cuda.Device().synchronize()
        transfer=time.perf_counter()-start;self.cache[key]=(d,dev)
        return dev,{'pack_s':packing,'h2d_s':transfer}
    def batch(self,d,queries):
        cp=self.cp;start=time.perf_counter();device,candidate_upload=self.upload(d)
        t=time.perf_counter();q=cp.asarray(np.ascontiguousarray(queries));out=cp.empty((len(queries),len(d['length']),10),dtype=cp.float64);cp.cuda.Device().synchronize();upload=time.perf_counter()-t
        events=[cp.cuda.Event(),cp.cuda.Event()];events[0].record();t=time.perf_counter()
        count=len(queries)*len(d['length']);self.kernel(((count+127)//128,),(128,),(device,q,out,np.int32(len(d['length'])),np.int32(len(queries))))
        events[1].record();events[1].synchronize();kernel=time.perf_counter()-t
        t=time.perf_counter();host=cp.asnumpy(out);cp.cuda.Device().synchronize();download=time.perf_counter()-t
        return host,{'candidate_upload_s':sum(candidate_upload.values()),'candidate_pack_s':candidate_upload['pack_s'],
            'candidate_h2d_s':candidate_upload['h2d_s'],'query_upload_alloc_s':upload,'device_wall_s':kernel,
            'device_event_s':cp.cuda.get_elapsed_time(*events)/1000,'download_s':download,'gpu_total_s':time.perf_counter()-start}
    def verified(self,d,target,start_anchor=None):
        start=time.perf_counter();gpu,record=self.batch(d,pack_q(target,start_anchor)[None,:])
        t=time.perf_counter();cpu=cpu_fit(d,target,start_anchor);packed=packed_cpu(cpu)
        error=float(np.max(np.abs(gpu[0]-packed))) if len(packed) else 0
        assert np.allclose(gpu[0],packed,rtol=1e-11,atol=1e-12),error
        self.max_error=max(self.max_error,error);self.verified_pairs+=len(packed)
        record.update(cpu_verify_s=time.perf_counter()-t,total_verified_s=time.perf_counter()-start,candidates=len(packed))
        self.records.append(record)
        # Every candidate is CPU checked: ties, thresholds and ordering exactly
        # match original. This conservative prototype measures that full cost.
        return cpu
