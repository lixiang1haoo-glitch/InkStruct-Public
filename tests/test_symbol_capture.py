import json
import sys

import pytest

from inkstruct.collector import _collector_source
from inkstruct.symbol_capture import (
    CAPTURE_CHARACTERS,
    CHARACTERS,
    FRAME,
    SymbolStorage,
    build_specimen,
    parse_symbol_file,
    symbol_info,
    write_catalog,
)

sys.path.insert(0, str(_collector_source()))
from handwriting_collector.models import Trajectory, TrajectoryPoint
from handwriting_collector.tasks import CollectionTask, TaskRepository


def specimen_args(character="g", strokes=1):
    task = CollectionTask.create("symbols", "test", "user_001", [(character, 5, 0)])
    trajectory = Trajectory()
    for i in range(strokes):
        trajectory.start_stroke(TrajectoryPoint(150, 150, 0.5, i * 20))
        trajectory.append_point(TrajectoryPoint(240, 280, 0.7, i * 20 + 10))
    return {
        "writer_id": task.writer_id,
        "task": task,
        "item": task.current_item(),
        "trajectory": trajectory,
        "canvas_width": 560,
        "canvas_height": 320,
        "device_pixel_ratio": 1.5,
    }


def test_catalog_and_roundtrip(tmp_path):
    assert len(set(CHARACTERS)) == len(CHARACTERS)
    assert all(c in CHARACTERS for c in "0123456789aAzZαΩφϕς−-∫√±≤")
    p = tmp_path / "catalog.csv"
    write_catalog(p)
    values = parse_symbol_file(p)
    assert [c for c, _, _ in values] == list(CAPTURE_CHARACTERS)
    assert all(n == 5 for _, n, _ in values)
    p = tmp_path / "subset.txt"
    p.write_text("A A φϕ −-", encoding="utf-8")
    assert [v[0] for v in parse_symbol_file(p)] == list("Aφϕ−-")
    p.write_text("永", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_symbol_file(p)


@pytest.mark.parametrize("character,strokes", [("4", 1), ("4", 3), ("A", 2), ("α", 1), ("=", 2), ("。", 1), ("“", 2), ("【", 1)])
def test_variable_strokes_raw_points_metrics_and_recovery(tmp_path, character, strokes):
    args = specimen_args(character, strokes)
    storage = SymbolStorage(tmp_path, lambda: "写法一")
    repository = TaskRepository(tmp_path)
    repository.save(args["task"])
    sid, path = storage.save_single(**args)
    p = json.loads(path.read_text(encoding='utf-8'))
    assert p["stats"]["stroke_count"] == strokes
    assert p["strokes"][0]["points"][-1] == {"x": 240.0, "y": 280.0, "pressure": 0.7, "t_ms": 10}
    assert p["metrics"]["descent_em"] == pytest.approx(0.15)
    assert p["metrics"]["advance_em"] == pytest.approx(0.58)
    assert p["guides"] == FRAME
    assert p["variant"]["note"] == "写法一"
    assert p["capture"]["device_pixel_ratio"] == 1.5
    recovered = repository.load(repository.path_for(args["task"].task_id))
    assert storage.reconcile_task(recovered) == 1
    assert recovered.items[0].sample_id == sid
    assert recovered.current_item().repeat_index == 2
    assert storage.reconcile_task(recovered) == 0
    assert not list(tmp_path.rglob("*.tmp"))


def test_validation_and_failed_publication(tmp_path, monkeypatch):
    args = specimen_args()
    with pytest.raises(ValueError):
        build_specimen(**(args | {"canvas_width": 600}))
    with pytest.raises(ValueError):
        build_specimen(**(args | {"writer_id": "../escape"}))
    storage = SymbolStorage(tmp_path)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("inkstruct.symbol_capture.os.replace", fail)
    with pytest.raises(OSError):
        storage.save_single(**args)
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.tmp"))
    assert args["task"].completed_count == 0


def test_greek_identity_and_contextual_math_classes():
    assert symbol_info("φ")["codepoint"] != symbol_info("ϕ")["codepoint"]
    assert symbol_info("−")["codepoint"] != symbol_info("-")["codepoint"]
    assert symbol_info("∫")["math_class_hint"] == "large_operator"
    assert symbol_info("|")["math_class_is_contextual"]
