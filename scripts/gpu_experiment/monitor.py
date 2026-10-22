"""Low-frequency process tree and NVML global telemetry; no process manipulation."""
import ctypes as c
import threading
import time
import psutil

class Memory(c.Structure):
    _fields_=[('total',c.c_ulonglong),('free',c.c_ulonglong),('used',c.c_ulonglong)]
class Util(c.Structure):
    _fields_=[('gpu',c.c_uint),('memory',c.c_uint)]

class Monitor:
    def __init__(self):
        self.rows=[];self.stop_event=threading.Event();self.proc=psutil.Process()
        self.nv=None;self.error=None
        try:
            self.nv=c.WinDLL('nvml.dll');assert self.nv.nvmlInit_v2()==0
            self.handle=c.c_void_p();assert self.nv.nvmlDeviceGetHandleByIndex_v2(0,c.byref(self.handle))==0
        except Exception as e:self.error=str(e);self.nv=None
    def sample(self):
        procs=[self.proc,*self.proc.children(recursive=True)]
        cpu=rss=0
        for p in procs:
            try:
                t=p.cpu_times();cpu+=t.user+t.system;rss+=p.memory_info().rss
            except psutil.Error:pass
        row={'time':time.perf_counter(),'cpu_seconds':cpu,'rss_bytes':rss}
        if self.nv:
            m=Memory();u=Util();w=c.c_uint()
            if self.nv.nvmlDeviceGetMemoryInfo(self.handle,c.byref(m))==0:row['global_vram_bytes']=m.used
            if self.nv.nvmlDeviceGetUtilizationRates(self.handle,c.byref(u))==0:row['global_gpu_percent']=u.gpu
            if self.nv.nvmlDeviceGetPowerUsage(self.handle,c.byref(w))==0:row['global_gpu_watts']=w.value/1000
        self.rows.append(row)
    def run(self):
        while not self.stop_event.is_set():
            self.sample();self.stop_event.wait(.2)
    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start();return self
    def stop(self):
        self.stop_event.set();self.thread.join();self.sample()
        return {'rows':self.rows,'nvml_error':self.error,'scope':'process tree CPU/RSS; GPU and VRAM are whole-device under WDDM'}
