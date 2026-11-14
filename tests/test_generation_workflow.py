"""Desktop method contract and readiness boundaries, independent of private archives."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from inkstruct.generation_workflow import METHODS, VERSION, GenerationWorkflow, workflow_version, write
from inkstruct.samples import sha256_file


def test_generation_parallelism_respects_requested_cpu_memory_and_job_size(monkeypatch):
    from inkstruct import generation_parallel
    from inkstruct.plotter import parallel

    monkeypatch.setattr(os, 'process_cpu_count', lambda: 20, raising=False)
    monkeypatch.setattr(parallel, 'available_memory', lambda: 32 * 1024**3)
    choose = generation_parallel.worker_count
    assert choose(127, 'auto') == 1
    assert choose(128, 'auto') == 4
    assert choose(128, 8) == 8
    assert choose(128, 32) == choose(128, 'max') == 18
    assert choose(3, 'max') == 3
    monkeypatch.setattr(os, 'process_cpu_count', lambda: 64)
    assert choose(128, 'max') == generation_parallel.MAX_WORKERS
    monkeypatch.setattr(parallel, 'available_memory', lambda: 4 * 1024**3)
    assert choose(128, 'max') == 6
    monkeypatch.setattr(parallel, 'available_memory', lambda: 1024**3)
    assert choose(128, 8) == 1
    with pytest.raises(ValueError, match='生成并发'):
        choose(128, generation_parallel.MAX_WORKERS + 1)


def test_missing_index_and_method_specific_state_do_not_enable_generation(tmp_path):
    source = tmp_path / 'samples'
    source.mkdir()
    db = tmp_path / 'structure'
    db.write_bytes(b'db')
    flow = GenerationWorkflow(tmp_path/'work', db)
    assert list(METHODS) == ['v63', 'v62', 'v61', 'v4', 'v631']
    ready = flow.readiness('alice', str(source), 'v4')
    assert ready['import'] and ready['start'] and not ready['profile'] and not ready['generate']
    with pytest.raises(ValueError, match='导入'):
        flow.build_profile('alice', str(source), 'v4')
    assert not flow.readiness('../other', str(source), 'v4')['import']
    index = tmp_path/'index.jsonl'
    index.write_text('{}\n')
    profile = tmp_path/'profile.json'
    profile.write_text('{}')
    state = {'import': {'index': str(index), 'index_sha256': sha256_file(index), 'accepted_count': 1},
             'profiles': {'v4': {'path': str(profile), 'workflow_version': VERSION,
                                'index_sha256': sha256_file(index)}}}
    write(flow.state_path('alice', source), state)
    assert flow.readiness('alice', str(source), 'v4')['generate']
    assert not flow.readiness('alice', str(source), 'v61')['generate']
    index.unlink()
    assert not flow.readiness('alice', str(source), 'v4')['generate']
    assert not flow.readiness('alice', str(source), 'v4')['profile']


def test_import_is_immutable_and_invalidates_profiles(tmp_path):
    source = tmp_path/'samples'
    source.mkdir()
    sample = {'schema_version':'handwriting_single_v1', 'sample_id':'one', 'writer_id':'alice',
              'character':'一', 'capture':{'canvas_width':100,'canvas_height':100},
              'strokes':[{'points':[{'x':20,'y':30,'pressure':.4,'t_ms':0},
                                   {'x':80,'y':30,'pressure':.5,'t_ms':50}]}]}
    (source/'one.json').write_text(json.dumps(sample))
    flow = GenerationWorkflow(tmp_path/'work', tmp_path/'no-db')
    flow.import_samples('alice', str(source), 'v4')
    state = flow.state('alice', source)
    old = Path(state['import']['index'])
    before = old.read_bytes()
    state['profiles'] = {'v4': {'pretend': 'old'}}
    write(flow.state_path('alice', source), state)
    flow.import_samples('alice', str(source), 'v4')
    new = flow.state('alice', source)
    assert new['import']['index'] != str(old) and old.read_bytes() == before
    assert not new['profiles']


def test_sample_change_status_and_failed_update_keep_successful_pair(tmp_path, monkeypatch):
    source = tmp_path / "samples"
    source.mkdir()
    path = source / "one.json"
    sample = {"schema_version": "handwriting_single_v1", "sample_id": "one", "writer_id": "alice",
              "character": "一", "capture": {"canvas_width": 100, "canvas_height": 100},
              "strokes": [{"points": [{"x": 20, "y": 30, "t_ms": 0}, {"x": 80, "y": 30, "t_ms": 50}]}]}
    path.write_text(json.dumps(sample), encoding="utf-8")
    flow = GenerationWorkflow(tmp_path / "work", tmp_path / "db")

    def profile(writer, method, batch):
        dest = Path(batch["index"]).with_name("profile.json")
        dest.write_text("{}", encoding="utf-8")
        return ({"path": str(dest), "index_sha256": batch["index_sha256"], "effective_donors": 1},
                {"message": "ready"})

    monkeypatch.setattr(flow, "_build_profile", profile)
    flow.update_samples("alice", source, "v4")
    old = flow.state("alice", source)
    status = flow.sample_status("alice", source, "v4")
    assert not status["changed"] and status["imported"] == status["donors"] == 1
    moved = path.with_name("moved.json")
    path.rename(moved)
    assert flow.sample_status("alice", source, "v4", status)["changed"]
    sample["strokes"][0]["points"][0]["x"] += 1
    moved.write_text(json.dumps(sample), encoding="utf-8")

    def fail(*_):
        raise ValueError("建档失败")

    monkeypatch.setattr(flow, "_build_profile", fail)
    with pytest.raises(ValueError, match="建档失败"):
        flow.update_samples("alice", source, "v4")
    assert flow.state("alice", source) == old
    assert Path(old["import"]["index"]).is_file()
    assert Path(old["profiles"]["v4"]["path"]).is_file()
    foreign = {**sample, "writer_id": "bob"}
    path.write_text(json.dumps(foreign), encoding="utf-8")
    assert flow.sample_status("alice", source, "v4", status)["foreign"] == ["bob"]
    with pytest.raises(ValueError, match="包含其他书写者"):
        flow.update_samples("alice", source, "v4")
    assert flow.state("alice", source) == old
    monkeypatch.setattr(flow, "_build_profile", profile)
    path.unlink()
    flow.update_samples("alice", source, "v4")
    assert not flow.sample_status("alice", source, "v4")["changed"]
    assert flow.state("alice", source)["import"]["index"] != old["import"]["index"]


def test_generation_prepares_only_what_changed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from inkstruct import generation_workflow, structures

    source = tmp_path / "samples"
    source.mkdir()
    db = tmp_path / "db"
    db.write_bytes(b"structures")
    sample = {"schema_version": "handwriting_single_v1", "sample_id": "one", "writer_id": "alice",
              "character": "一", "capture": {"canvas_width": 100, "canvas_height": 100},
              "strokes": [{"points": [{"x": 20, "y": 30, "t_ms": 0}, {"x": 80, "y": 30, "t_ms": 50}]}]}
    write(source / "one.json", sample)
    flow = GenerationWorkflow(tmp_path / "work", db)
    stages, used_profiles = [], []

    def build(writer, method, batch):
        path = tmp_path / f"{len(stages)}-{method}.json"
        write(path, {"method": method})
        return ({"path": str(path), "sha256": sha256_file(path), "index_sha256": batch["index_sha256"],
                 "workflow_version": workflow_version(method), "database_sha256": sha256_file(db)},
                {"message": "建档完成", "profile": str(path)})

    def generate(output, writer, characters, base, profile, *_args, **_kwargs):
        used_profiles.append(profile)
        return {"completed_count": 1, "completed_preview": "一", "failed_count": 0}

    monkeypatch.setattr(flow, "_build_profile", build)
    monkeypatch.setattr(generation_workflow, "corrections", lambda: [])
    monkeypatch.setattr(generation_workflow, "generate_v61", generate)
    monkeypatch.setattr(structures, "StructureRepository", lambda path: SimpleNamespace(characters=lambda: ["一"]))

    def start(method="v62", cancelled=lambda: False):
        return flow.generate("alice", source, method, "一",
                             preparation=lambda stage, _: stages.append(stage), cancelled=cancelled)

    assert start()["completed_preview"] == "一"
    assert stages == ["核对样本", "导入样本", "建档", "建档完成", "生成字形"]
    first = flow.state("alice", source)
    stages.clear()
    start()
    assert stages == ["核对样本", "沿用档案", "生成字形"]
    assert flow.state("alice", source) == first and used_profiles[0] == used_profiles[1]
    stages.clear()
    start("v61")
    assert stages == ["核对样本", "建档", "建档完成", "生成字形"]
    previous = flow.state("alice", source)
    assert previous["import"] == first["import"]
    assert set(previous["profiles"]) == {"v61", "v62"}

    write(source / "two.json", {**sample, "sample_id": "two"})
    with monkeypatch.context() as patch:
        def fail(*_):
            raise ValueError("模拟建档失败")
        patch.setattr(flow, "_build_profile", fail)
        with pytest.raises(ValueError, match="模拟建档失败"):
            start()
    assert flow.state("alice", source) == previous and len(used_profiles) == 3
    stages.clear()
    result = start(cancelled=lambda: "建档" in stages)
    assert result["status"] == "cancelled" and "output" not in result
    assert flow.state("alice", source) == previous and len(used_profiles) == 3
    start()
    assert flow.state("alice", source)["import"]["accepted_count"] == 2
    assert Path(used_profiles[0]["path"]).is_file() and Path(first["import"]["index"]).is_file()


def test_ui_default_readiness_and_error_has_no_traceback(tmp_path):
    code = r'''
from pathlib import Path
import sys,time
from PySide6 import QtCore, QtWidgets
from inkstruct.desktop import main
from inkstruct.generation_targets import target_manifest
app=QtWidgets.QApplication([])
w=main(['check'], create_only=True, workspace=Path(sys.argv[1]), database=Path(sys.argv[1])/'no-db')
f=w.centralWidget()
assert [f.method.itemData(i) for i in range(f.method.count())] == ['v63', 'v62', 'v61', 'v4', 'v631']
assert f.method.currentData()=='v63'
assert 'v6.3 和 v6.3.1 支持连笔' in ''.join(x.text() for x in f.findChildren(QtWidgets.QLabel))
assert f.candidate_limit.isEnabled()
assert f.same_character.isChecked()
assert not f.source_score.isChecked() and not f.diversity_score.isChecked()
f.source_score.setChecked(True)
assert not f.diversity_score.isChecked()
f.diversity_score.setChecked(True)
f.source_score.setChecked(False)
assert f.diversity_score.isChecked()
assert not f.generate_button.isEnabled()
assert not hasattr(f,'trajectory_mode') and not hasattr(f,'source_profile')
assert 'CUDA' not in ''.join(x.text() for x in f.findChildren(QtWidgets.QLabel))
f.completed({'message':'已选字表','target_manifest':target_manifest('孔正','孔正')})
f.do_generate()
end=time.monotonic()+5
while f.busy and time.monotonic()<end:
    app.processEvents();time.sleep(.01)
assert not f.busy
assert 'Traceback' not in f.log.toPlainText()
assert '目录' in f.log.toPlainText()
assert not f.generate_button.isEnabled()
done={'message':'完成','output':'test-run','completed_count':0}
f.completed({**done,'scores':{'source_score':100,'replayed_count':1}})
assert '来源分 100.00' in f.score_summary.text() and '多样性分' not in f.score_summary.text()
f.completed({**done,'scores':{'diversity_score':0,'covered_count':0,'target_count':2,'rotatable_count':0}})
assert '多样性分 0.00' in f.score_summary.text() and '来源分' not in f.score_summary.text()
f.completed(done)
assert f.score_summary.isHidden()
f.method.setCurrentIndex(1)
fresh=main(['check'], create_only=True, workspace=Path(sys.argv[1]))
assert fresh.centralWidget().method.currentData()=='v63'
QtCore.QThreadPool.globalInstance().waitForDone()
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], env={**os.environ,'QT_QPA_PLATFORM':'offscreen'}, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr


def test_background_sample_scan_does_not_show_previous_author(tmp_path):
    code = r'''
from pathlib import Path
from threading import Event
from unittest.mock import patch
import sys,time
from PySide6 import QtCore, QtWidgets
from inkstruct.desktop import main
from inkstruct.generation_workflow import GenerationWorkflow

root = Path(sys.argv[1])
for author in ("alice", "bob"):
    (root / "samples" / author).mkdir(parents=True)
app = QtWidgets.QApplication([])
w = main(["test"], create_only=True, workspace=root, database=root/"db")
f = w.centralWidget()
f.capture_root_provider = lambda: root
from inkstruct.capture_management import CaptureCatalog
from inkstruct.generation_workflow import write
catalog = CaptureCatalog(root)
state = catalog.read()
state["writers"]["alice"] = {"name": "甲"}
write(catalog.index, state)
f.writer.reload()
assert f.writer.isEditable() and f.writer.findData("bob") >= 0
entered, release = Event(), Event()

def scan(self, writer, source, method, previous):
    if writer == "alice":
        entered.set()
        assert release.wait(3)
    return {"path": source, "imported_at": None, "imported": 3 if writer == "alice" else 7,
            "donors": 2, "foreign": [], "changed": False}

with patch.object(GenerationWorkflow, "sample_status", scan):
    f.writer.setCurrentIndex(f.writer.findData("alice"))
    assert f.writer.text() == "alice" and "甲" in f.writer.currentText()
    assert entered.wait(2)
    f.writer.setCurrentIndex(f.writer.findData("bob"))
    assert f.sample_status is None
    assert Path(f.samples.text()) == root / "samples" / "bob"
    release.set()
    end = time.monotonic() + 5
    while f.sample_status is None and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    assert f.sample_status["imported"] == 7
    assert "bob" in f.sample_summary.text() and "alice" not in f.sample_summary.text()
    f.writer.setText("external.id")
    assert f.writer.text() == "external.id" and f.writer.findData("external.id") == -1
QtCore.QThreadPool.globalInstance().waitForDone()
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, encoding='utf-8', timeout=15, check=False)
    assert result.returncode == 0, result.stderr
