"""Real spawn processes use identical validators and cleanly finish or fail."""

import multiprocessing
import os
from pathlib import Path

import pytest
from test_font_packages import recorded

from inkstruct.fonts import library, parallel_verify
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font


@pytest.fixture
def font_path(tmp_path):
    path = tmp_path / 'original.inkfont'
    build_font(path, writer='fixture', name='parallel check', symbols=recorded(tmp_path))
    return path


def _crash_worker(*args):
    os._exit(7)


def test_worker_budget_and_small_font_serial(monkeypatch):
    monkeypatch.setattr(parallel_verify.os, "process_cpu_count", lambda: 18, raising=False)
    assert parallel_verify.worker_count(2) == 1
    assert parallel_verify.worker_count(20000) == 4
    assert parallel_verify.worker_count(20000, 99) == 4
    monkeypatch.setattr(parallel_verify.os, "process_cpu_count", lambda: 1)
    assert parallel_verify.worker_count(20000) == 1
    with pytest.raises(ValueError):
        parallel_verify.worker_count(20000, 0)


def test_parallel_statistics_and_import_bytes_match_serial(font_path, tmp_path):
    expected = FontPackage(font_path).verify()
    telemetry, progress = {}, []
    actual = parallel_verify.verify_font(
        FontPackage(font_path, verify_all=False),
        workers=2,
        progress=progress.append,
        telemetry=telemetry,
    )
    assert actual == expected
    assert telemetry["workers"] >= 1 and telemetry["worker_cpu_seconds"] >= 0
    if telemetry["workers"] > 1:
        assert telemetry["worker_pids"] and telemetry["worker_cpu_seconds"] > 0
    assert not multiprocessing.active_children()
    result = library.import_font(font_path, tmp_path / "library", workers=2)
    assert result["verification"] == expected
    assert Path(result["path"]).read_bytes() == font_path.read_bytes()
    assert not multiprocessing.active_children()


def test_pool_start_failure_does_not_publish_or_fallback(font_path, tmp_path, monkeypatch):
    def fail(*a, **k):
        raise OSError("worker start denied")

    monkeypatch.setattr(parallel_verify, "ProcessPoolExecutor", fail)
    monkeypatch.setattr(parallel_verify, "worker_count", lambda *a: 2)
    with pytest.raises(OSError, match="worker start denied"):
        library.import_font(font_path, tmp_path / "library")
    assert not list((tmp_path / "library").iterdir())


def test_dead_worker_does_not_publish_or_leave_children(font_path, tmp_path, monkeypatch):
    # A spawn initializer deliberately exits before sending any successful result.
    from concurrent.futures.process import BrokenProcessPool

    monkeypatch.setattr(parallel_verify, "_initialize", _crash_worker)
    monkeypatch.setattr(parallel_verify, "worker_count", lambda *a: 2)
    with pytest.raises(BrokenProcessPool):
        library.import_font(font_path, tmp_path / "library")
    assert not list((tmp_path / "library").iterdir())
    assert not multiprocessing.active_children()
