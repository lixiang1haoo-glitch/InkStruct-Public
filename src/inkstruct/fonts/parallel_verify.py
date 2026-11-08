"""Bounded spawn workers verify disjoint candidate ranges of one staged font."""

import atexit
import multiprocessing
import os
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

from .core import FontPackage

MAX_WORKERS = 4
BATCH_SIZE = 128
PARALLEL_THRESHOLD = 512
_font = _archive = None


def worker_count(candidates, requested=None):
    available = max(1, (getattr(os, "process_cpu_count", os.cpu_count)() or 1) - 1)
    if requested is None and candidates < PARALLEL_THRESHOLD:
        return 1
    if requested is not None and (type(requested) is not int or requested < 1):
        raise ValueError("无效的字体验证进程数")
    return min(MAX_WORKERS, available, requested or MAX_WORKERS, max(1, candidates))


def _initialize(path, content_hash):
    global _font, _archive
    _font = FontPackage(path, verify_all=False)
    if _font.manifest["content_hash"] != content_hash:
        raise ValueError("字体文件已变化，请重新导入")
    _archive = zipfile.ZipFile(path)
    atexit.register(_archive.close)


def _batch(bounds):
    start, end = bounds
    points = gaps = 0
    styles = {"upright": 0, "italic": 0, "unspecified": 0}
    for record in _font.records[start:end]:
        point_count, gap, style = _font._verify_record(_archive, record)
        points += point_count
        gaps += gap
        if style in styles:
            styles[style] += 1
    return start, end, points, gaps, styles, os.getpid(), time.process_time()


def verify_font(font, *, progress=None, workers=None, telemetry=None):
    total = len(font.records)
    count = worker_count(total, workers)
    if telemetry is not None:
        telemetry.update(workers=count, worker_cpu_seconds=0.0, worker_pids=[])
    if count == 1:
        return font.verify(progress=progress)
    if font.fingerprint != (font.path.stat().st_size, font.path.stat().st_mtime_ns):
        raise ValueError("字体文件已变化，请重新导入")
    if progress:
        progress(f"正在启动 {count} 个验证进程…")
    points = gaps = completed = 0
    styles = {"upright": 0, "italic": 0, "unspecified": 0}
    cpu, seen = {}, set()
    batch_size = min(BATCH_SIZE, max(1, (total + count * 4 - 1) // (count * 4)))
    bounds = [(start, min(start + batch_size, total)) for start in range(0, total, batch_size)]
    executor = ProcessPoolExecutor(
        max_workers=count,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize,
        initargs=(str(font.path.resolve()), font.manifest["content_hash"]),
    )
    futures = {}
    try:
        futures = {executor.submit(_batch, item): item for item in bounds}
        last_progress = 0.0
        for future in as_completed(futures):
            start, end, batch_points, batch_gaps, batch_styles, pid, used = future.result()
            if (start, end) != futures[future] or (start, end) in seen:
                raise ValueError("字体并行验证返回不完整或重复结果")
            seen.add((start, end))
            completed += end - start
            points += batch_points
            gaps += batch_gaps
            for key in styles:
                styles[key] += batch_styles[key]
            cpu[pid] = max(cpu.get(pid, 0), used)
            now = time.monotonic()
            if progress and (now - last_progress >= 0.1 or completed == total):
                progress(f"正在验证字形 {completed}/{total}（{count} 个进程）…")
                last_progress = now
        if seen != set(bounds) or completed != total:
            raise ValueError("字体并行验证结果不完整")
    finally:
        # A failed candidate or dead worker never becomes a successful import.
        # Cancel pending work; wait only for already running bounded batches.
        executor.shutdown(wait=True, cancel_futures=True)
    if progress:
        progress("正在核对其余字体成员…")
    font._verify_remaining()
    if telemetry is not None:
        telemetry.update(worker_cpu_seconds=sum(cpu.values()), worker_pids=sorted(cpu))
    return font._verification_statistics(completed, points, gaps, styles)
