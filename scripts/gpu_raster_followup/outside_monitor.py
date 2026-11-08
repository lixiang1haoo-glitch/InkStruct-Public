"""Put psutil/NVML sampling in another process, outside the GUI's Python GIL."""
import bootstrap as b
import json
import os
import subprocess
import sys
import time
import uuid

class Monitor:
    def __init__(self):
        self.token=uuid.uuid4().hex
        self.path=b.OUT/'tmp'/f'monitor-{self.token}.json'
        self.stop_path=b.OUT/'tmp'/f'monitor-{self.token}.stop'
    def start(self):
        self.child=subprocess.Popen([sys.executable,str(b.ROOT/'scripts/gpu_raster_followup/outside_monitor.py'),str(os.getpid()),str(self.path),str(self.stop_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return self
    def stop(self):
        self.stop_path.touch();self.child.wait(timeout=10)
        assert self.child.returncode==0
        return json.loads(self.path.read_text(encoding='utf-8'))

if __name__=='__main__':
    import ctypes as c
    import psutil
    from monitor import Memory,Util
    from pathlib import Path
    target=psutil.Process(int(sys.argv[1]));output=Path(sys.argv[2]);stop=Path(sys.argv[3]);own=psutil.Process()
    nv=None;error=None;handle=c.c_void_p();rows=[];cpu_by_pid={}
    try:
        nv=c.WinDLL('nvml.dll');assert nv.nvmlInit_v2()==0;assert nv.nvmlDeviceGetHandleByIndex_v2(0,c.byref(handle))==0
    except Exception as e:error=str(e);nv=None
    while not stop.exists():
        started=time.perf_counter();rss=0
        for p in [target,*target.children(recursive=True)]:
            if p.pid==own.pid:continue
            try:
                t=p.cpu_times();cpu_by_pid[p.pid]=t.user+t.system;rss+=p.memory_info().rss
            except psutil.Error:pass
        row={'time':time.perf_counter(),'sample_start':started,'cpu_seconds':sum(cpu_by_pid.values()),'rss_bytes':rss}
        if nv:
            m=Memory();u=Util();w=c.c_uint()
            if nv.nvmlDeviceGetMemoryInfo(handle,c.byref(m))==0:row['global_vram_bytes']=m.used
            if nv.nvmlDeviceGetUtilizationRates(handle,c.byref(u))==0:row['global_gpu_percent']=u.gpu
            if nv.nvmlDeviceGetPowerUsage(handle,c.byref(w))==0:row['global_gpu_watts']=w.value/1000
        row['sample_end']=time.perf_counter();rows.append(row)
        time.sleep(max(.001,.2-(time.perf_counter()-started)))
    t=own.cpu_times()
    output.write_text(json.dumps({'rows':rows,'nvml_error':error,'sampler_process_cpu_s':t.user+t.system,
        'scope':'external sampler; target tree CPU and RSS, sampler excluded; GPU/VRAM whole-device under WDDM'}),encoding='utf-8')
