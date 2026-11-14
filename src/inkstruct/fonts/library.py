"""Verified, atomic library import; no Qt or layout glyph allocation."""

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .core import FontPackage
from .identity import release_identity
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


def find_font_release(root, identity):
    """Find an exact release by bounded manifest reads; the caller verifies it fully."""
    from .core import MAX_MEMBER, decode

    matches = []
    for path in Path(root).glob('*.inkfont'):
        try:
            stamp = fingerprint(path)
            with ZipFile(path) as archive, archive.open('manifest.json') as stream:
                raw = stream.read(MAX_MEMBER + 1)
            if len(raw) <= MAX_MEMBER and release_identity(decode(raw)) == identity:
                matches.append((stamp[3], path))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, BadZipFile):
            continue
    return max(matches)[1] if matches else None


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


def publish_font(root, *, writer, run, symbols, name, package_kind, groups, stamp, expected, progress, rules=None,
                 writer_links=None):
    """Build and fully verify on the library volume before creating its visible entry."""
    from ..generation_workflow import identity, write
    from .importer import build_font
    from .publication import candidate_coverage, require_publication_stamp, writer_authorizer
    from .publication_rules import PublicationRules

    rules = rules or PublicationRules()

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    log = root.parent / "publication-logs" / (identity() + ".json")
    timings = {}
    current = started = None

    def phase(label):
        nonlocal current, started
        now = time.perf_counter()
        if current is not None:
            timings[current] = round(now - started, 4)
        current, started = label, now
        if label:
            progress(label + "…")

    def rows(coverage):
        return [[*key, value] for key, value in sorted(coverage.items())]

    def record(status, **details):
        try:
            write(log, {"status": status, "writer": writer, "name": name, "run": str(run or ""),
                        "symbols": str(symbols or ""), "groups": sorted(groups), "timings_s": timings,
                        "expected": rows(expected), "disabled_rules": sorted(rules.disabled),
                        "enabled_rules": sorted(rules.enabled), "rule_families": dict(rules.families),
                        "borrowed_donors": [{"target": choice.target, "sample_id": choice.sample_id,
                                             "sha256": choice.sha256} for choice in rules.donors], **details})
        except OSError:
            return ""
        return str(log)

    diagnostics = []
    try:
        phase("准备字形")
        require_publication_stamp(writer, run, symbols, stamp)
        with tempfile.TemporaryDirectory(prefix=".publication-", dir=root, ignore_cleanup_errors=True) as folder:
            staged = Path(folder) / "font.inkfont"
            selected_symbols = symbols if groups - {"han"} else None
            build_font(staged, writer=writer, name=name, run=run if "han" in groups else None,
                       symbols=selected_symbols, symbol_groups=groups if symbols else None,
                       package_kind=package_kind, phase=phase, diagnostics=diagnostics, rules=rules,
                       authorize_symbols=writer_authorizer(writer, run, writer_links),
                       progress=lambda message: progress("准备字形 · " + message))
            phase("完整验证")
            font = FontPackage(staged, verify_all=False)
            stats = font.verify(progress=lambda message: progress("完整验证 · " + message))
            actual = candidate_coverage(font.records, font.provenance)
            difference = {key: actual[key] - expected[key] for key in actual.keys() | expected.keys()
                          if actual[key] != expected[key]}
            details = entry(font)
            target = root / (font.manifest["package_id"] + ".inkfont")
            require_publication_stamp(writer, run, symbols, stamp)
            phase("入库")
            os.link(staged, target)
    except Exception as error:
        failed_phase = current
        phase(None)
        path = record("failed", phase=failed_phase, error=str(error), diagnostics=diagnostics)
        raise ValueError(f"{failed_phase}失败 · {error}" + (f"\n记录：{path}" if path else "")) from error
    phase(None)
    path = record("published", path=str(target), actual=rows(actual), difference=rows(difference),
                  statistics=stats, diagnostics=diagnostics)
    return {"path": str(target), "entry": (fingerprint(target), *details), "published": True,
            "verification": stats, "coverage": actual, "difference": difference,
            "timings": timings, "log": path}
