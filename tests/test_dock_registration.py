"""Physical position evidence and the Windows single-sheet workflow."""
import os
from pathlib import Path
from dataclasses import replace
from time import monotonic, sleep
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from inkstruct.document.flow_template import FlowTemplate
from inkstruct.document.template_authoring import parse_template, template_json
from inkstruct.document.template_revision import version_template
from inkstruct.plotter.docking import DockTrial, dock_from_mark, idle_checkpoint, restored_frame
from inkstruct.plotter.grbl import Status
from inkstruct.plotter.profiles import DeviceAxes, DeviceDatum, DeviceProfile, PageAlignment, PlotterProfiles


def reading(x, y, *, state="Idle", offset=(0., 0., 0.)):
    return Status(state, (x, y, 0.), offset, "")


def device():
    p = DeviceProfile.create("N1", "sim", "usb-id")
    return replace(p, datum=replace(DeviceDatum.create(p, "停靠点"), boot_mode="retained"))


@pytest.mark.parametrize("initial,values,mode", [
    ((9, 8), [(0, 0)] * 3, "zero"),
    ((3, 7), [(3, 7), (3.001, 7), (3, 7)], "retained"),
    ((0, 0), [(3, 7)] * 3, ""),
    ((3, 7), [(3, 7), (0, 0), (3, 7)], ""),
])
def test_physical_power_cycles(initial, values, mode):
    trial = DockTrial("dev", initial, "before")
    with pytest.raises(ValueError):
        trial.record_restart("before", reading(*initial))
    for i, xy in enumerate(values):
        if i == 2 and not mode:
            with pytest.raises(ValueError, match="1035966437"):
                trial.record_restart(str(i), reading(*xy))
        else:
            trial.record_restart(str(i), reading(*xy))
    assert trial.mode == mode


def test_idle_proof_and_recovery(tmp_path):
    p, store = device(), PlotterProfiles(tmp_path)
    proof = idle_checkpoint(p, (-60, -60), reading(20, 35))
    store.exchange_checkpoint(p, proof)
    saved = PlotterProfiles(tmp_path).exchange_checkpoint(p)
    assert restored_frame(p, saved, reading(20.005, 35)) == (-60, -60)
    assert restored_frame(p, saved, reading(21, 35)) is None
    assert restored_frame(p, saved, reading(0, 0)) is None
    assert restored_frame(p, saved, reading(20, 35, offset=None)) is None
    assert restored_frame(p, saved, reading(20, 35, offset=(0, 1, 0))) is None
    assert restored_frame(p, None, reading(20, 35)) is None
    assert restored_frame(device(), saved, reading(20, 35)) is None
    assert restored_frame(p, {"xy": [20, 35]}, reading(20, 35)) is None
    for state in ("Hold:0", "Alarm", "Run"):
        with pytest.raises(ValueError):
            idle_checkpoint(p, (-60, -60), reading(20, 35, state=state))
    assert dock_from_mark(p.axes, (80, 95), (20, 35)) == (-60, -60)
    for axes in (DeviceAxes(2, .5, True, False, True), DeviceAxes(.7, 1.1, False, True)):
        datum = replace(p.datum, axes=axes)
        origin = dock_from_mark(axes, (80, 95), (20, 35))
        assert datum.to_body((20, 35), origin) == pytest.approx((80, 95), abs=.002)


def test_local_geometry_and_both_serializers(tmp_path):
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.editing import SourceSession
    from inkstruct.document.package import load_package, save_package
    from inkstruct.document.schema import PageProfile, StyleProfile
    from inkstruct.document.styles import FlowStyle
    from inkstruct.editor.machine_alignment import page_context

    p = device()
    store = PlotterProfiles(tmp_path)
    first = version_template(FlowTemplate(plotter_alignment=PageAlignment((4, 16))))
    key = page_context(first)[0]
    store.save_sheet(p, key, (4, 16), (80, 95), 1)
    assert store.sheet(device(), key) is None
    assert page_context(replace(first, name="新名字"))[0] == key
    assert page_context(FlowTemplate())[0] != page_context(FlowTemplate())[0]
    assert page_context(FlowTemplate.ordinary())[0] == page_context(FlowTemplate.ordinary())[0]
    simple = FlowTemplate(name='独立简单模板')
    renamed = version_template(replace(simple, name='新名字'), parent=simple)
    assert page_context(simple)[0] == page_context(renamed)[0]
    assert page_context(version_template(FlowTemplate()))[0] != key
    assert page_context(replace(first, width_mm=220))[0] != key
    assert page_context(first, index=3)[0] == key
    template_file = tmp_path / "template.json"
    template_file.write_text(template_json(first), encoding="utf-8")
    doc = tmp_path / "test.inkdoc"
    save_package(doc, SourceSession("12"), AssetResolver(builtin_numbers=True), PageProfile(),
                 StyleProfile(), flow=FlowStyle(template=first))
    with ZipFile(doc) as z:
        styles = z.read("styles.json").decode("utf-8")
    for raw in (template_file.read_text("utf-8"), styles):
        for field in ("paper_origins", "plotter_alignment", "virtual", "generation", "boot_mode"):
            assert field not in raw
    for reopened in (parse_template(template_file.read_text("utf-8")), load_package(doc).flow.template):
        assert page_context(reopened)[0] == key
        assert reopened.paper_origin(reopened.layout(0)) is None
        assert store.sheet(p, key)["virtual"] == [80, 95]


def test_legacy_inkdoc_opens_for_migration_without_replacing_original(tmp_path, monkeypatch):
    from dataclasses import asdict
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document import package
    from inkstruct.document.editing import SourceSession
    from inkstruct.document.styles import FlowStyle
    from inkstruct.document.schema import PageProfile, StyleProfile

    mark = PageAlignment((10, 12))
    source = tmp_path / "old.inkdoc"
    with monkeypatch.context() as m:
        # Produce the unversioned inner record used by historical files.
        m.setattr(package, "template_record", lambda template, record: {k: v for k, v in asdict(template).items()
                                                                      if k not in ("revision", "family_id")})
        package.save_package(source, SourceSession("12"), AssetResolver(builtin_numbers=True),
                             PageProfile(), StyleProfile(), flow=FlowStyle(template=FlowTemplate(plotter_alignment=mark)))
    original = source.read_bytes()
    old = package.load_package(source)
    assert "另存" in old.migration_notice and old.flow.template.paper_origin(old.flow.template.layout(0)) == mark
    target = tmp_path / "new.inkdoc"
    package.save_package(target, old.session, old.resolver, old.page, old.style, flow=old.flow)
    clean = package.load_package(target)
    assert not clean.migration_notice and clean.flow.template.family_id == old.flow.template.family_id
    assert package.load_package(source).flow.template.family_id == old.flow.template.family_id
    assert source.read_bytes() == original


def test_selected_page_dock_reconnect_and_abort(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.editor.machine_devices import DeviceDialog
    from inkstruct.plotter.qt_connection import N1Worker
    from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp
    from test_plotter_machine import SimulatedGrbl

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    serial = SimulatedGrbl()
    port = SimpleNamespace(portName=lambda: "sim", serialNumber=lambda: "usb-id")
    def transport(_port):
        serial.closed = False
        return serial
    panel = MachinePanel(None, worker_factory=lambda w: N1Worker(w, serial_factory=transport),
                         ports=lambda: [port])
    panel.set_workspace(tmp_path)
    panel.save_profile(DeviceProfile.create("N1", "sim", "usb-id"))
    panel.confirm = lambda *_: True
    template = FlowTemplate()
    pages = tuple(Page(i, (), (PaintOp(str(i), ((6+i, 7.), (8+i, 9.)), .3),)) for i in range(3))
    snap = LayoutSnapshot("s", "k", "doc", 0, template.page, pages, (), "r", "t")
    panel.show()
    panel.set_document(snap, 1, True, template)

    def wait():
        end = monotonic() + 12
        while monotonic() < end:
            app.processEvents()
            if not panel.busy:
                app.processEvents()  # queued zero-position confirmation
                if not panel.busy:
                    break
            sleep(.002)
        assert panel.busy is None, panel.report.text()

    def reconnect():
        panel.toggle_connection()
        wait()
        assert panel.device is None
        panel.toggle_connection()
        wait()
        assert panel.device is not None

    try:
        panel.toggle_connection()
        wait()
        assert panel.frame is None and not panel.dry_button.isEnabled()
        assert not panel.park_at_datum()
        assert not any(cmd.startswith(b"G1") for cmd in serial.commands)
        dialog = DeviceDialog(panel)
        assert panel.capture_position(panel.begin_dock_trial, datum=True)
        wait()
        for _ in range(3):
            reconnect()
            assert panel.capture_position(panel.record_restart, datum=True)
            wait()
        assert panel.dock_trial.mode == "zero" and not panel.datum_located
        assert panel.submit("axis-trial", panel.profile.axes, None, panel.profile.feed, None)
        wait()
        old = panel.store.path.read_bytes()
        def denied(*_args):
            raise PermissionError("simulated unwritable profile")
        with monkeypatch.context() as m:
            m.setattr(panel.store, "save", denied)
            with pytest.raises(PermissionError):
                panel.initialize_axes(panel.profile.axes, None)
        assert not panel.datum_located and panel.store.path.read_bytes() == old
        panel.initialize_axes(panel.profile.axes, None)
        assert panel.datum_located and panel.frame == (0, 0)
        assert panel.store.devices()[0].datum.restart_positions == ((0, 0),) * 4
        assert not panel.write_button.isEnabled()
        assert panel.jog(1, 0) is None
        wait()
        key = panel.sheet_context()[0]
        mark = PageAlignment((5, 5))
        assert panel.capture_position(lambda st: panel.measure_sheet(key, mark, st), datum=True)
        wait()
        saved = panel.store.sheet(panel.profile, key)
        measured = tuple(serial.position[:2])
        assert panel.job.index == 1
        assert panel.job.registration.place((7, 7)) == (measured[0]+2, measured[1]+2)
        panel.follow_page(2)
        assert panel.job.index == 2 and panel.job.registration.origin == measured
        panel.jog(1, 0)
        wait()
        assert panel.capture_position(lambda st: panel.measure_sheet(key, mark, st, temporary=True), datum=True)
        wait()
        assert panel.job.registration.origin == (measured[0]+1, measured[1]) and panel.store.sheet(panel.profile, key) == saved
        panel.follow_page(1)
        assert panel.job.registration.origin == measured and panel.temporary is None
        assert panel.run_job("dry")
        wait()
        assert panel.run_job("write")
        wait()
        assert panel.page_list.currentRow() == 1 and panel.completed_pages == {1}
        assert panel.done == 1 and panel.journal.read() == (1, False)
        assert panel.frame == tuple(serial.position[:2]) and "可以取纸" in panel.report.text()
        panel.confirm = lambda *_: False
        offered = []
        def defer_choice(_parent, _title, _prompt, choices, *_args):
            offered.extend(choices)
            return "", False
        monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", defer_choice)
        reconnect()
        assert offered and offered[-1] == "重新初始化…"
        assert not panel.datum_located and panel.job is None
        panel.jog(1, 0)
        wait()
        assert panel.capture_position(lambda st: panel.measure_sheet(key, mark, st, recovery=True), datum=True)
        wait()
        assert panel.datum_located and panel.store.sheet(panel.profile, key) == saved
        reconnect()
        assert panel.datum_located and panel.done == 1
        # Start another sheet. A failure committing its lifted stroke keeps the
        # connection and its frame. Reconnection alone must not resume writing.
        from inkstruct.plotter.physical import WorkArea
        import json
        replace_file = os.replace
        progress_path = panel.journal.path
        def fail_completion(source, destination):
            if Path(destination) == progress_path and not json.loads(Path(source).read_bytes())["check_stroke"]:
                raise PermissionError(13, "progress file busy")
            return replace_file(source, destination)
        with monkeypatch.context() as m:
            m.setattr(os, "replace", fail_completion)
            assert panel.run_job("write", local_area=WorkArea(-100, -100, 100, 100)), panel.report.text()
            wait()
        assert panel.device and panel.frame == tuple(serial.position[:2])
        assert "保存失败" in panel.report.text() and "已确认抬笔回停靠点" in panel.report.text()
        assert panel.journal.read() == (0, True) and not panel.completed_pages
        before = len(serial.commands)
        reconnect()
        assert panel.datum_located and panel.uncertain and panel.done == 0
        assert not any(command.startswith(b"G1 ") for command in serial.commands[before:])
        assert panel.run_job("write", start=0)  # Explicit decision to rewrite the checked stroke.
        wait()
        assert panel.journal.read() == (1, False)
        # The previous proof was consumed. Failure to save a clean disconnect
        # at a nonzero position cannot revive that proof on the next open.
        with monkeypatch.context() as m:
            m.setattr(panel.store, "exchange_checkpoint", denied)
            panel.toggle_connection()
            wait()
        panel.toggle_connection()
        wait()
        assert not panel.datum_located and panel.job is None
        assert panel.capture_position(lambda st: panel.restore_from_sheet(key, mark, st), datum=True)
        wait()
        assert panel.submit("position-datum")
        wait()
        panel.begin_dock_trial(panel.device)
        panel.cancel_dock_trial()
        assert not panel.datum_located and panel.store.sheet(panel.profile, key) == saved
        before = list(serial.commands)
        assert not panel.submit("return", (0, 0), None, 500)
        assert serial.commands == before
        # Re-open on zero: only an affirmative physical observation can bind it.
        serial.position[:] = [0., 0., 0.]
        panel.confirm = lambda *_: True
        panel.toggle_connection()
        wait()
        panel.toggle_connection()
        wait()
        wait()
        assert panel.datum_located and panel.job.index == 1
        # A known reset on emergency stop must not leave a nonzero proof,
        # even if W and WCO happen to agree on the next connection.
        serial.on_write = lambda data: panel.worker.control.stop_requested.set() if data.startswith(b"G1 X") else None
        with monkeypatch.context() as m:
            m.setattr(panel.store, "exchange_checkpoint", denied)
            assert panel.run_job("dry")
            wait()
        assert not panel.device and panel.frame is None
        assert b"!" in serial.commands and b"\x18" in serial.commands
        assert "可以取纸" not in panel.report.text()
        panel.confirm = lambda *_: False
        serial.on_write = lambda data: None
        panel.toggle_connection()
        wait()
        assert not panel.datum_located and not panel.job and panel.done == 1
        # A failed credential write never licenses another move. Emergency stop
        # uses the worker event; it is independent of profile storage.
        panel.toggle_connection()
        wait()
        before = list(serial.commands)
        with monkeypatch.context() as m:
            m.setattr(panel.store, "exchange_checkpoint", denied)
            panel.toggle_connection()
            assert not panel.device and serial.commands == before
        dialog.close()
    finally:
        panel.shutdown()
        panel.close()


def test_unrelated_legacy_simple_template_files_do_not_share_a_measurement(tmp_path):
    import json
    from inkstruct.document.template_authoring import read_template
    from inkstruct.editor.machine_alignment import page_context

    data = json.loads(template_json(FlowTemplate()))
    data.pop("family_id")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for file in (a, b):
        file.write_text(json.dumps(data), encoding="utf-8")
    template = read_template(a)
    original = page_context(template)[0]
    assert page_context(read_template(a))[0] == original
    assert page_context(read_template(b))[0] != original
    renamed = tmp_path / "renamed.json"
    renamed.write_text(template_json(replace(template, name="Renamed")), encoding="utf-8")
    assert page_context(read_template(renamed))[0] == original


def test_clean_window_close_away_from_dock_restores_full_mapping(tmp_path):
    from PySide6 import QtWidgets
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.plotter.qt_connection import N1Worker
    from test_plotter_machine import SimulatedGrbl

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    p = device()
    store = PlotterProfiles(tmp_path)
    store.save(p)
    key = "archived-layout"
    mark = PageAlignment((10., 15.))
    store.save_sheet(p, key, mark.a, (80, 95), 3, layout={"family": "other-template",
                     "title": "实验报告 · 第 3 页", "size": [210, 297]})
    serial = SimulatedGrbl()
    serial.position[:] = [20., 35., 0.]

    def wait(panel):
        end = monotonic() + 5
        while panel.busy and monotonic() < end:
            app.processEvents()
            sleep(.002)
        assert not panel.busy, panel.report.text()

    def opened():
        serial.closed = False
        port = SimpleNamespace(portName=lambda: p.port, serialNumber=lambda: p.serial)
        panel = MachinePanel(None, ports=lambda: [port],
                             worker_factory=lambda w: N1Worker(w, serial_factory=lambda _: serial))
        panel.set_workspace(tmp_path)
        panel.toggle_connection()
        wait(panel)
        return panel

    panel = opened()
    try:
        assert not panel.datum_located
        assert panel.capture_position(lambda st: panel.restore_from_sheet(key, mark, st), datum=True)
        wait(panel)
        assert panel.frame == (-60., -60.) and panel.frame != tuple(serial.position[:2])
    finally:
        panel.shutdown()
        panel.close()
    assert store.read()["reconnect_positions"][p.id]["xy"] == [20., 35.]
    panel = opened()
    try:
        assert panel.frame == (-60., -60.) and panel.datum_located
        assert panel.store.sheet(panel.profile, key)["virtual"] == [80., 95.]
        assert not any(line.startswith(b"G1") for line in serial.commands)
        panel.rename_device(p.id, "同一台设备")
        assert panel.datum_located and panel.frame == (-60., -60.)
        assert panel.profile.accepts_sheet(panel.store.sheet(panel.profile, key))
    finally:
        panel.shutdown()
        panel.close()
