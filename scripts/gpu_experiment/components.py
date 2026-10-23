"""Capture actual component fits, compare batched NumPy and FP64 CUDA.

Variable stroke counts remain grouped; anisotropic post-transform resampling,
admission and full trajectory validation remain CPU authoritative.
"""
import bootstrap as b
import json
import time
from collections import defaultdict
import numpy as np
import cupy as cp
from inkstruct.contextual_trajectory import anchors
from inkstruct.generation_workflow import generate_v61
from inkstruct import v61_candidate_expansion as expansion
from inkstruct.structures import StructureRepository
from inkstruct.samples import sha256_file
from monitor import Monitor

monitor=Monitor().start();captured=[];original={}
for name in ('fit_shared_similarity','fit_bounded_axes'):
    old=getattr(expansion,name);original[name]=old
    def capture(source,target,_old=old,_name=name):
        # Preserve invalid inputs too: GPU is never allowed to erase a rejection.
        x,y=anchors(source),anchors(target)
        row={'name':_name,'x':x.tolist(),'y':y.tolist()}
        try:
            result=_old(source,target);row['accepted']=True
            row['transform']=[result.sx,result.sy,result.tx,result.ty];return result
        except ValueError as e:row.update(accepted=False,error=str(e));raise
        finally:captured.append(row)
    setattr(expansion,name,capture)
start=time.perf_counter()
profile=b.ROOT/'artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json'
try:
    generated=generate_v61(b.OUT/'component-capture-run','user_001',list('孔正址兄礼烧止怔歪羊群'),
        StructureRepository(),{'path':str(profile),'sha256':sha256_file(profile)},lambda r:print(r,flush=True),lambda:False,semantic=True)
finally:
    for name,old in original.items():setattr(expansion,name,old)
capture_s=time.perf_counter()-start
b.save('component-fit-inputs.json',captured)
groups=defaultdict(list)
for row in captured:groups[(row['name'],len(row['x']))].append(row)

def numpy_fit(x,y,axis):
    xm=x.mean(axis=1);ym=y.mean(axis=1);xc=x-xm[:,None,:];yc=y-ym[:,None,:]
    if axis:
        den=np.sum(xc*xc,axis=1);scale=np.sum(xc*yc,axis=1)/np.maximum(den,1e-300)
    else:
        den=np.sum(xc*xc,axis=(1,2));s=np.sum(xc*yc,axis=(1,2))/np.maximum(den,1e-300);scale=np.column_stack((s,s))
    offset=ym-scale*xm
    return np.column_stack((scale,offset)),den

code=r'''
extern "C" __global__ void fit(const double* x,const double* y,double* out,int Q,int K,int axis){
 int q=blockIdx.x*blockDim.x+threadIdx.x;if(q>=Q)return; x+=q*K*2;y+=q*K*2;
 double xm=0,xn=0,ym=0,yn=0;for(int k=0;k<K;k++){xm+=x[k*2];xn+=x[k*2+1];ym+=y[k*2];yn+=y[k*2+1];}
 xm/=K;xn/=K;ym/=K;yn/=K;double nx=0,ny=0,dx=0,dy=0;
 for(int k=0;k<K;k++){double a=x[k*2]-xm,b=x[k*2+1]-xn;nx+=a*(y[k*2]-ym);ny+=b*(y[k*2+1]-yn);dx+=a*a;dy+=b*b;}
 double sx=axis?nx/fmax(dx,1e-300):(nx+ny)/fmax(dx+dy,1e-300),sy=axis?ny/fmax(dy,1e-300):sx;
 out[q*4]=sx;out[q*4+1]=sy;out[q*4+2]=ym-sx*xm;out[q*4+3]=yn-sy*xn;
}
'''
kernel=cp.RawKernel(code,'fit',options=('--fmad=false',));cp.cuda.Device().synchronize()
packed=[];initial=0
for (name,k),rows in groups.items():
    x=np.asarray([r['x'] for r in rows]);y=np.asarray([r['y'] for r in rows]);axis=name=='fit_bounded_axes'
    t=time.perf_counter();xd,yd=cp.asarray(x),cp.asarray(y);out=cp.empty((len(x),4),dtype=cp.float64);cp.cuda.Device().synchronize();initial+=time.perf_counter()-t
    # Compile/warm once, then all measurements wait for actual completion.
    kernel(((len(x)+127)//128,),(128,),(xd,yd,out,np.int32(len(x)),np.int32(k),np.int32(axis)));cp.cuda.Device().synchronize()
    packed.append((x,y,xd,yd,out,axis,k,rows))
records=[];max_error=0
for rep in range(7):
    row={};t=time.perf_counter()
    expected=[numpy_fit(x,y,axis) for x,y,xd,yd,out,axis,k,rows in packed]
    row['numpy_batch_s']=time.perf_counter()-t
    start=time.perf_counter();events=[cp.cuda.Event(),cp.cuda.Event()];events[0].record()
    for x,y,xd,yd,out,axis,k,rows in packed:
        kernel(((len(x)+127)//128,),(128,),(xd,yd,out,np.int32(len(x)),np.int32(k),np.int32(axis)))
    events[1].record();events[1].synchronize();row['device_s']=cp.cuda.get_elapsed_time(*events)/1000
    t=time.perf_counter();answers=[cp.asnumpy(item[4]) for item in packed];cp.cuda.Device().synchronize();row['download_s']=time.perf_counter()-t
    row['resident_gpu_fit_download_s']=time.perf_counter()-start
    t=time.perf_counter()
    for a,(cpu,den),item in zip(answers,expected,packed,strict=True):
        assert np.allclose(a,cpu,rtol=1e-11,atol=1e-12)
        max_error=max(max_error,float(np.max(abs(a-cpu))))
        # Retain original CPU admission: no GPU scale sign / 1.35 cutoff decision.
        for actual,trace in zip(cpu,item[-1],strict=True):
            if trace['accepted']:assert np.allclose(actual,trace['transform'],rtol=1e-11,atol=1e-12)
    row['cpu_output_check_s']=time.perf_counter()-t
    # A deployable path recomputes all uncertain transforms and re-runs the
    # existing score/resampling downstream. Account full CPU batch recomputation.
    t=time.perf_counter()
    for x,y,xd,yd,out,axis,k,rows in packed:numpy_fit(x,y,axis)
    row['cpu_authoritative_recompute_s']=time.perf_counter()-t
    row['safe_fit_total_s']=row['resident_gpu_fit_download_s']+row['cpu_authoritative_recompute_s']
    records.append(row)
b.save('component-stage.json',{'capture_generation_s':capture_s,'generation':generated,'fit_pairs':len(captured),
    'groups':len(groups),'point_counts':sorted(set(k for name,k in groups)),'accepted':sum(r['accepted'] for r in captured),
    'initial_descriptor_upload_s':initial,'max_abs_error':max_error,'records':records,'monitor':monitor.stop(),
    'scope':'real 11-character component fit inputs; no full-library component-pool extrapolation; scores and geometry stay CPU'})
print('component batch',len(captured),records,flush=True)
