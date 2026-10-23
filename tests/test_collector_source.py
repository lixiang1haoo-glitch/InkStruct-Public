import pytest

from inkstruct import collector


def test_collector_source_explicit_override_and_invalid_override(tmp_path, monkeypatch):
    source = tmp_path / "external kernel"
    (source / "handwriting_collector").mkdir(parents=True)
    (source / "handwriting_collector" / "ui.py").write_text("")
    monkeypatch.setenv("INKSTRUCT_COLLECTOR_SOURCE", str(source))
    assert collector._collector_source() == source
    monkeypatch.setenv("INKSTRUCT_COLLECTOR_SOURCE", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="INKSTRUCT_COLLECTOR_SOURCE"):
        collector._collector_source()


def test_collector_discovers_ignored_local_kernel(tmp_path, monkeypatch):
    monkeypatch.delenv("INKSTRUCT_COLLECTOR_SOURCE", raising=False)
    monkeypatch.setattr(collector, "PROJECT_ROOT", tmp_path)
    source = tmp_path / "artifacts" / "external" / "data_collection"
    (source / "handwriting_collector").mkdir(parents=True)
    (source / "handwriting_collector" / "ui.py").write_text("")
    assert collector._collector_source() == source
