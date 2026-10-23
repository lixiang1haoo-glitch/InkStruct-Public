"""Verified, atomic library import; no Qt or layout glyph allocation."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from .core import FontPackage
from .parallel_verify import verify_font


def entry(font):
    m = font.manifest
    counts = {
        style: len({r["character"] for r in font.records if r["letter_style"] == style})
        for style in ("upright", "italic", "unspecified")
    }
    warnings = sum(s["author_source_status"] != "complete" for s in font.provenance.values())
    title = f"{m['name']} · {m['writer_alias']} · {len(font.pools)} 字 · {'用户版' if m['package_kind'] == 'user' else '开发者版'}"
    detail = (
        f"{len(font.records)} 份候选 · 来源提示 {warnings} 份\n"
        f"英文正体 {counts['upright']}/52 · 斜体 {counts['italic']}/52 · 未分类 {counts['unspecified']}"
    )
    return title, detail


def fingerprint(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def import_font(source, root, progress=lambda message: None, *, workers=None):
    """Copy once, fully verify the staged snapshot once, then publish without overwrite."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    progress("正在复制字体到临时导入区…")
    with tempfile.TemporaryDirectory(dir=root) as temp:
        staged = Path(temp) / "import.inkfont"
        shutil.copyfile(source, staged)
        progress("正在读取字体索引…")
        font = FontPackage(staged, verify_all=False)
        telemetry = {}
        stats = verify_font(font, progress=progress, workers=workers, telemetry=telemetry)
        target = root / (font.manifest["package_id"] + ".inkfont")
        details = entry(font)
        progress("正在加入字体库…")
        try:
            os.link(staged, target)
        except FileExistsError:
            # Never silently accept a different/damaged file with the same ID.
            if file_digest(staged) != file_digest(target):
                raise ValueError(
                    "字体库中存在同一包 ID 的不同文件；原文件保留，请先核查。"
                ) from None
    # Removing the staging hard link changes ctime on Windows. Stamp the final
    # file after cleanup so the UI does not immediately re-read its full index.
    return {
        "path": str(target),
        "entry": (fingerprint(target), *details),
        "verification": stats,
        "verification_runtime": telemetry,
        "message": f"字体已导入 · {stats['characters']} 字，{stats['candidates']} 份候选",
    }
