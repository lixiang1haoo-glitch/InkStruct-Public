import bootstrap as b
import contextlib
import io
import time
start=time.perf_counter()
import cupy as cp
import numpy as np
config=io.StringIO()
with contextlib.redirect_stdout(config):cp.show_config()
t=time.perf_counter();cp.cuda.Device(0).use();cp.cuda.Device().synchronize();init=time.perf_counter()-t
t=time.perf_counter();kernel=cp.RawKernel('extern "C" __global__ void twice(const double* a,double* b){int i=blockDim.x*blockIdx.x+threadIdx.x;if(i<32)b[i]=2*a[i];}', 'twice',options=('--fmad=false',))
a=cp.asarray(np.arange(32,dtype=np.float64));out=cp.empty_like(a);kernel((1,),(32,),(a,out));cp.cuda.Device().synchronize();ans=cp.asnumpy(out);assert np.array_equal(ans,np.arange(32)*2)
b.save('cuda-probe.json',{'config':config.getvalue(),'context_seconds':init,'first_compile_upload_kernel_readback_seconds':time.perf_counter()-t,'total_seconds':time.perf_counter()-start,'result':ans.tolist()})
print(config.getvalue());print('CUDA FP64 kernel correct',flush=True)
