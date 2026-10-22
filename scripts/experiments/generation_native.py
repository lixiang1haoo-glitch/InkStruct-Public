"""Actual generation widget/QRunnable responsiveness probe, isolated workspace.

QTest transactions target an extra experiment-only input. Their paint endpoint
is a real widget paint followed by DwmFlush, not an optical scanout measurement.
"""
import concurrent.futures as futures
import ctypes
import multiprocessing as mp
from pathlib import Path
import sys
import time
import threading

sys.path.insert(0,str(Path(__file__).resolve().parent))
from generation_parallel import OUT,ROOT,PROFILE,DATABASE,SMALL,initialize,compute,save,digest
from PySide6 import QtCore,QtWidgets,QtTest
from inkstruct.desktop import main as generation_window
from inkstruct.theme import use_light_theme


def main():
    app=QtWidgets.QApplication([]);use_light_theme(app)
    folder=OUT/(sys.argv[1] if len(sys.argv)>1 else 'native');folder.mkdir(exist_ok=False)
    window=generation_window(['experiment'],create_only=True,workspace=folder/'private-workspace',database=DATABASE)
    window.setWindowTitle('InkStruct 字集并行可行性实验 · 非发布版本')
    window.resize(1000,760)
    widget=window.centralWidget()
    foreground=ctypes.WinDLL('user32').GetForegroundWindow;foreground.restype=ctypes.c_void_p
    flush=ctypes.WinDLL('dwmapi').DwmFlush
    report={'endpoint':'QTest text transaction, actual QLineEdit paint then DwmFlush; no optical scanout claim',
            'trials':[],'foreground_required':True}
    active=[None];pending=[]
    class Input(QtWidgets.QLineEdit):
        def paintEvent(self,event):
            super().paintEvent(event)
            if pending:
                flush();now=time.perf_counter()
                if active[0] is not None:
                    for started in pending:active[0]['input_to_paint_ms'].append((now-started)*1000)
                pending.clear()
    probe=Input();probe.setPlaceholderText('实验输入探针（不改变作者档案或生成目标）')
    widget.layout().insertWidget(1,probe)
    start_button=QtWidgets.QPushButton('开始测量（约 3 分钟，期间请保持此窗口在前台）')
    widget.layout().insertWidget(1,start_button)
    consent=[False]
    start_button.clicked.connect(lambda:consent.__setitem__(0,True))
    window.show();window.raise_();window.activateWindow();probe.setFocus()
    last=[time.perf_counter()]
    heartbeat=QtCore.QTimer();heartbeat.setInterval(16)
    def beat():
        now=time.perf_counter()
        if active[0] is not None:
            active[0]['heartbeat_ms'].append((now-last[0])*1000)
            active[0]['foreground'].append(foreground()==int(window.winId()))
        last[0]=now
    heartbeat.timeout.connect(beat);heartbeat.start()
    inputs=QtCore.QTimer();inputs.setInterval(250)
    def typing():
        if active[0] is not None:
            pending.append(time.perf_counter());QtTest.QTest.keyClicks(probe,'1')
            if len(probe.text())>40:probe.clear()
    inputs.timeout.connect(typing);inputs.start()
    def pump(test,timeout=150):
        start=time.perf_counter()
        while not test():
            app.processEvents();time.sleep(.002)
            if time.perf_counter()-start>timeout:raise TimeoutError('native trial timeout')
    inactive='--event-loop-only' in sys.argv
    report['event_loop_only']=inactive
    try:
        if not inactive:pump(lambda:consent[0] and foreground()==int(window.winId()),300)
    except Exception:
        import traceback
        report['error']=traceback.format_exc();save(folder/'measurements.json',report);raise
    start_button.setEnabled(False);start_button.setText('测量中；完成后窗口自动关闭')
    report.update(window=[window.width(),window.height()],dpi=window.screen().logicalDotsPerInch(),
                  device_pixel_ratio=window.devicePixelRatioF(),screen=window.screen().name())
    try:
        for repeat in range(2):
            for mode,workers in [('baseline-qthread',1),('process',2),('process',4)]:
                label=f'{mode}{workers}-{repeat}'
                row={'label':label,'heartbeat_ms':[],'input_to_paint_ms':[],'foreground':[]}
                active[0]=row;last[0]=time.perf_counter();start=time.perf_counter()
                def work(mode=mode,workers=workers,label=label):
                    output=folder/label
                    if mode=='baseline-qthread':
                        from inkstruct.generation_workflow import generate_v61
                        from inkstruct.structures import StructureRepository
                        result=generate_v61(output,'user_001',list(SMALL),StructureRepository(DATABASE),
                            {'path':str(PROFILE),'sha256':digest(PROFILE)},widget.generation_progress.emit,
                            lambda:False,semantic=True)
                    else:
                        cls=futures.ProcessPoolExecutor if mode=='process' else futures.ThreadPoolExecutor
                        options={'mp_context':mp.get_context('spawn')} if mode=='process' else {}
                        records=[]
                        with cls(workers,initializer=initialize,**options) as executor:
                            jobs=[executor.submit(compute,(c,str(output),None)) for c in SMALL]
                            for future in futures.as_completed(jobs):
                                records.append(future.result())
                                widget.generation_progress.emit({'completed_count':len(records),'requested_count':len(SMALL),
                                    'failed_count':sum(r['status']=='failed' for r in records),'character':records[-1]['character']})
                        result={'completed_count':len(records),'results':records}
                    return {**result,'message':'实验批次完成；所有来源提示保留于实验结果'}
                widget.submit(work,cancellable=False)
                pump(lambda:not widget.busy)
                app.processEvents();flush()
                row['wall_s']=time.perf_counter()-start
                row['foreground_fraction']=sum(row['foreground'])/max(1,len(row['foreground']))
                row['foreground_valid']=row['foreground_fraction']>=.95
                row['status']=widget.status.text();row['log']=widget.log.toPlainText()
                report['trials'].append(row);active[0]=None
                save(folder/'measurements.json',report)
                window.grab().save(str(folder/(label+'.png')))
                print(label,round(row['wall_s'],2),'foreground',round(row['foreground_fraction'],3),flush=True)
        report['passed']=all(r['foreground_valid'] and '操作未完成' not in r['log'] for r in report['trials'])
    except Exception:
        import traceback
        report['error']=traceback.format_exc();raise
    finally:
        save(folder/'measurements.json',report);window.close()


if __name__=='__main__':
    mp.freeze_support();main()
