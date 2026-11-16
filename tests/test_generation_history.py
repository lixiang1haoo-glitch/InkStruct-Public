"""Use synthetic source ink and a real v6.3.1 batch to exercise history."""

import os
import time
from pathlib import Path

import pytest

from inkstruct import generation_workflow as workflow
from inkstruct.generation_history import Recording, SourceArchive, StrokeSource, batch_history, inspect_candidates
from inkstruct.samples import sha256_file

from test_v63_connected import record, setup


@pytest.fixture
def batches(setup, tmp_path, monkeypatch):
    repo, graph, references = setup
    monkeypatch.setattr(workflow, "corrections", lambda: references)
    raw = tmp_path / "raw"
    connected = record(raw / "connected.json", graph, join=0)
    record(raw / "separate.json", graph)
    service = workflow.GenerationWorkflow(tmp_path / "workspace", repo.path)
    result = service.generate("alice", raw, "v631", "明", workers=1, candidate_limit=3,
                              preparation=lambda *_: None)
    path = Path(result["output"])
    assert result["completed_count"] == 1
    legacy = service.root / "outputs" / "bob" / "older-run"
    workflow.write(legacy / "manifest.json", {"writer_id": "bob", "completed_characters": "明丶"})
    workflow.write(legacy / "trajectories" / "U+660E.json", {
        "writer_id": "bob", "character": "明", "generator": "v4",
        "strokes": [{"points": [{"x": 0.3, "y": 0.4}, {"x": 0.6, "y": 0.7}]}],
    })
    workflow.write(legacy / "trajectories" / "U+4E36.json", {
        "writer_id": "bob", "character": "丶", "generator": "v4",
        "strokes": [{"points": [{"x": 0.5, "y": 0.3}, {"x": 0.53, "y": 0.36}]}],
    })
    return service, path, legacy, connected


def test_history_preserves_connected_and_legacy_granularity(batches):
    service, path, legacy, connected = batches
    by_writer = {b["writer"]: b for b in batch_history(service.root / "outputs")}
    assert by_writer["alice"]["path"] == path and by_writer["bob"]["path"] == legacy
    candidates = list(inspect_candidates(by_writer["alice"], "明"))
    assert len(candidates) >= 2
    _, segments, profile = next(item for item in candidates if len(item[1][0].slots) > 1)
    originals = SourceArchive("alice", profile, service.root / "imports", service.workspace / "capture")
    resolved, recordings = originals.resolve(segments)
    first = resolved[0]
    assert first.slots == ("s1", "s2")
    assert (first.character, first.sample, first.raw_order, first.kind) == ("明", "connected", 1, "整字复用")
    assert recordings[first.key].strokes[0] == tuple((p.x, p.y) for p in connected.strokes[0].points)
    assert recordings[first.key].status == "原录制"
    original = Path(connected.source_path)
    assert sha256_file(original) == connected.source_sha256
    original.unlink()
    _, missing = originals.resolve(segments)
    assert missing[first.key].strokes == recordings[first.key].strokes
    assert "原文件缺失" in missing[first.key].status
    _, unavailable = SourceArchive("alice", {}, service.root / "imports", service.workspace / "capture").resolve(segments)
    assert unavailable[first.key].strokes == ()
    _, older, _ = next(inspect_candidates(by_writer["bob"], "明"))
    assert older[0].kind == "来源未记录" and older[0].raw_order is None


def test_nonmodal_history_from_generation_panel(batches, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    pytest.importorskip("PySide6")
    from PySide6 import QtCore, QtTest, QtWidgets

    from inkstruct.desktop import main

    service, path, _, _ = batches
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def wait_for(predicate):
        until = time.monotonic() + 8
        while not predicate():
            app.processEvents()
            time.sleep(.005)
            assert time.monotonic() < until

    window = main(["InkStruct"], create_only=True, workspace=service.workspace, database=service.database)
    widget = window.centralWidget()
    widget.writer.setText("alice")
    received = []
    widget.history_publish_requested.connect(lambda p, w: received.append((p, w)))
    window.show()
    assert not widget.last_generated_run and widget.history_button.isEnabled()
    widget.history_button.click()
    dialog = widget.history_dialog
    try:
        assert dialog.isVisible() and not dialog.isModal()
        wait_for(lambda: bool(dialog.strokes))
        assert dialog.writers.currentData() == "alice"
        assert dialog.batch_list.count() == 1
        dialog.search.setText("U+660E")
        wait_for(lambda: bool(dialog.strokes))
        assert dialog.candidate.count() >= 2
        joined = next(i for i, candidate in enumerate(dialog.candidates) if len(candidate[1][0].slots) > 1)
        dialog.candidate.setCurrentIndex(joined)
        wait_for(lambda: bool(dialog.strokes))
        assert dialog.stroke_table.item(0, 1).text() == "s1 + s2"
        dialog.stroke_table.setCurrentCell(1, 0)
        assert dialog.source_cards[dialog.strokes[1].key].preview.selected == dialog.strokes[1].raw_order - 1
        wait_for(lambda: bool(dialog.generated.paths))
        position = dialog.generated.display_path(0).pointAtPercent(.15).toPoint()
        QtTest.QTest.mouseClick(dialog.generated, QtCore.Qt.MouseButton.LeftButton, pos=position)
        assert dialog.stroke_table.currentRow() == 0 and dialog.source_cards[dialog.strokes[0].key].preview.selected == 0
        dialog.copy.click()
        copied = app.clipboard().text()
        assert all(s in copied for s in (path.name, "明", "候选", "s1 + s2", "connected", "原笔序 1"))
        dialog.font_button.click()
        assert received == [(path, "alice")] and widget.last_generated_run is None
        dialog.writers.setCurrentIndex(0)
        assert dialog.batch_list.count() == 2
        dialog.batch_list.setCurrentRow(next(i for i, batch in enumerate(dialog.visible) if batch["writer"] == "bob"))
        assert dialog.character_model.rowCount() == 2
        dot = dialog.character_model.index(dialog.characters.index("丶"))
        QtTest.QTest.mouseClick(dialog.character.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                pos=dialog.character.visualRect(dot).center())
        wait_for(lambda: dialog.current_character() == "丶" and bool(dialog.strokes))
        assert not dialog.source_cards
        assert dialog.generated.display_path(0).boundingRect().height() < dialog.generated.height() / 10
    finally:
        dialog.close()
        QtCore.QThreadPool.globalInstance().waitForDone()
        window.close()


def test_source_grid_links_exact_recordings_and_shares_view(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6 import QtCore, QtGui, QtTest, QtWidgets

    from inkstruct.generation_history_ui import GenerationHistoryDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = GenerationHistoryDialog(tmp_path, tmp_path, "")
    dialog.resize(1180, 680)
    dialog.show()
    QtCore.QThreadPool.globalInstance().waitForDone()
    app.processEvents()
    dialog.batch = {"path": tmp_path}
    first = StrokeSource(("s1",), ((.29, .25), (.32, .30)), "单笔拼接", "永", "a", "digest-a", raw_order=2)
    second = StrokeSource(("s2", "s3"), ((.5, .6), (.68, .67)), "部件复用", "林", "b", "digest-b", raw_order=1)
    missing = StrokeSource(("s4",), ((.48, .38), (.68, .39)), "单笔拼接", "林", "c", "digest-c", raw_order=3)
    a = Recording((((744, 86), (812, 90), (846, 103)), ((775, 120), (796, 137))), "原录制", (1600, 260))
    b = Recording((((5, 5),),), "原录制", (200, 100))
    try:
        dialog.show_strokes([first, second, missing], {first.key: a, second.key: b})
        app.processEvents()
        one, two, unavailable = (dialog.source_cards[stroke.key] for stroke in (first, second, missing))
        assert one.isVisible() and two.isVisible() and unavailable.isVisible()
        assert one.preview.paths[0].boundingRect().width() == pytest.approx(102 / 156)
        assert one.preview.paths[0].elementAt(2).isCurveTo()
        assert b.framed_strokes("林") == (((.5, .5),),)
        punctuation = b.framed_strokes("、")[0][0]
        assert punctuation == pytest.approx((.025, .275))
        assert one.preview.selected == 1 and two.preview.selected == -1
        assert two.preview.has_ink() and not unavailable.preview.has_ink()
        target = dialog.generated
        position = target.display_path(1).pointAtPercent(.5)
        QtTest.QTest.mouseClick(target, QtCore.Qt.MouseButton.LeftButton, pos=position.toPoint())
        assert dialog.stroke_table.currentRow() == 1 and two.preview.selected == 0
        assert two.button.isChecked() and not one.button.isChecked() and one.preview.selected == -1
        unavailable.button.click()
        assert unavailable.button.isChecked() and not two.button.isChecked()
        assert "未找到原录制" in dialog.source_note.text() and unavailable.preview.selected == -1
        viewport = one.preview
        anchor = QtCore.QPointF(viewport.width() * .47, viewport.height() * .35)
        before = viewport.drawing_transform().inverted()[0].map(anchor)
        event = QtGui.QWheelEvent(anchor, viewport.mapToGlobal(anchor), QtCore.QPoint(), QtCore.QPoint(0, 120),
                                  QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.ControlModifier,
                                  QtCore.Qt.ScrollPhase.NoScrollPhase, False)
        app.sendEvent(viewport, event)
        after = viewport.drawing_transform().inverted()[0].map(anchor)
        assert QtCore.QLineF(before, after).length() < 1e-9
        assert dialog.zoom_button.text() == "120%" and target.view is viewport.view is two.preview.view
        center = QtCore.QPointF(dialog.view.center)
        start = target.rect().center()
        end = start + QtCore.QPoint(29, 18)
        QtTest.QTest.mousePress(target, QtCore.Qt.MouseButton.LeftButton, pos=start)
        move = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(end),
                                 QtCore.QPointF(target.mapToGlobal(end)), QtCore.Qt.MouseButton.NoButton,
                                 QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        app.sendEvent(target, move)
        QtTest.QTest.mouseRelease(target, QtCore.Qt.MouseButton.LeftButton, pos=end)
        assert dialog.view.center != center and dialog.stroke_table.currentRow() == 2
        QtTest.QTest.mouseClick(target, QtCore.Qt.MouseButton.LeftButton,
                                pos=target.display_path(1).pointAtPercent(.5).toPoint())
        assert dialog.stroke_table.currentRow() == 1 and two.preview.selected == 0
        dialog.zoom_button.click()
        assert dialog.zoom_button.text() == "100%" and dialog.view.center == QtCore.QPointF(.5, .5)
        initial_height = one.preview.height()
        dialog.resize(dialog.width(), dialog.height() + 180)
        app.processEvents()
        assert one.preview.height() > initial_height
    finally:
        dialog.close()


def test_preview_curve_preserves_endpoints_dots_and_local_corners():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QPointF

    from inkstruct.generation_history_ui import preview_path

    start, end = (.2, .2), (.5, .7)
    path = preview_path((start, start, (.5, .2), end))
    assert path.pointAtPercent(0) == QPointF(*start)
    assert path.pointAtPercent(1) == QPointF(*end)
    assert path.elementAt(1).x == pytest.approx(.475)
    assert path.elementAt(2).isCurveTo()
    assert path.elementAt(4).y == pytest.approx(.225)
    dot = preview_path((start, start))
    assert dot.isEmpty() and dot.currentPosition() == QPointF(*start)
    assert preview_path((start, end)).elementCount() == 2
