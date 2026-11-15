"""Use synthetic source ink and a real v6.3.1 batch to exercise history."""

import os
import time
from pathlib import Path

import pytest

from inkstruct import generation_workflow as workflow
from inkstruct.generation_history import SourceArchive, batch_history, inspect_candidates
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
    workflow.write(legacy / "manifest.json", {"writer_id": "bob", "completed_characters": "明"})
    workflow.write(legacy / "trajectories" / "U+660E.json", {
        "writer_id": "bob", "character": "明", "generator": "v4",
        "strokes": [{"points": [{"x": 0.3, "y": 0.4}, {"x": 0.6, "y": 0.7}]}],
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
        assert dialog.batches_table.rowCount() == 1
        dialog.search.setText("U+660E")
        wait_for(lambda: bool(dialog.strokes))
        assert dialog.candidate.count() >= 2
        joined = next(i for i, candidate in enumerate(dialog.candidates) if len(candidate[1][0].slots) > 1)
        dialog.candidate.setCurrentIndex(joined)
        wait_for(lambda: bool(dialog.strokes))
        assert dialog.stroke_table.item(0, 1).text() == "s1 + s2"
        dialog.stroke_table.setCurrentCell(1, 0)
        assert dialog.original.selected == dialog.strokes[1].raw_order - 1
        wait_for(lambda: bool(dialog.generated.paths))
        position = dialog.generated.paths[0].pointAtPercent(.15).toPoint()
        QtTest.QTest.mouseClick(dialog.generated, QtCore.Qt.MouseButton.LeftButton, pos=position)
        assert dialog.stroke_table.currentRow() == 0 and dialog.original.selected == 0
        dialog.copy.click()
        copied = app.clipboard().text()
        assert all(s in copied for s in (path.name, "明", "候选", "s1 + s2", "connected", "原笔序 1"))
        dialog.font_button.click()
        assert received == [(path, "alice")] and widget.last_generated_run is None
        dialog.writers.setCurrentIndex(0)
        assert dialog.batches_table.rowCount() == 2
    finally:
        dialog.close()
        QtCore.QThreadPool.globalInstance().waitForDone()
        window.close()
