"""Verified, atomic library import; no Qt or layout glyph allocation."""

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .core import FontPackage, exchange_manifest, latin, package_manifest
from . import capacity, exchange_codec
from .identity import release_identity
from .parallel_verify import verify_font


def entry(font):
    m = font.manifest
    counts = {
        style: len({r["character"] for r in font.records if latin(r["character"]) and r["letter_style"] == style})
        for style in ("upright", "italic", "unspecified")
    }
    warnings = sum(s["author_source_status"] != "complete" for s in font.provenance.values())
    kind = {"user": "用户版", "developer": "开发者版", "exchange": "统一字库 v1"}[m["package_kind"]]
    if capacity.local_package(m) or (m["package_kind"] != "exchange" and len(font.records) > exchange_codec.MAX_CANDIDATES):
        kind += " · 本机大容量"
    title = f"{m['name']} · {m['writer_alias']} · {len(font.pools)} 字 · {kind}"
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
    from itertools import chain
    from .exchange import identity as exchange_identity

    matches = []
    for path in chain(Path(root).glob('*.inkfont'), (Path(root) / 'originals').glob('*.inkfont')):
        try:
            stamp = fingerprint(path)
            with ZipFile(path) as archive:
                manifest = package_manifest(archive)
            if exchange_manifest(manifest):
                manifest = exchange_identity(manifest)
            if release_identity(manifest) == identity:
                matches.append((stamp[3], path))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, BadZipFile):
            continue
    return max(matches)[1] if matches else None


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def publish_copy(staged, target):
    try:
        os.link(staged, target)
    except FileExistsError:
        if file_digest(staged) != file_digest(target):
            raise ValueError("字体库中存在同一包 ID 的不同文件；原文件保留，请先核查。") from None


class LocalFontConsent(ValueError):
    def __init__(self, count, content_hash):
        super().__init__("导入本机大容量字体需要确认")
        self.count, self.content_hash = count, content_hash


def import_font(source, root, progress=lambda message: None, *, workers=None, include_dynamics=False,
                approved_hash=None, convert_installed=False):
    """Verify the source snapshot and publish an exchange copy or a validated legacy fallback."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = Path(source)
    if convert_installed and source.resolve().parent != root.resolve():
        raise ValueError("请选择字体库内的原包")
    if approved_hash is None:
        with ZipFile(source) as archive:
            manifest = package_manifest(archive)
        if not exchange_manifest(manifest) and capacity.local_package(manifest):
            count = manifest.get("candidate_count")
            if type(count) is not int or count <= 0:
                count = len(FontPackage(source, verify_all=False).records)
            raise LocalFontConsent(count, manifest["content_hash"])
    progress("正在复制字体到临时导入区…")
    with tempfile.TemporaryDirectory(dir=root) as temp:
        staged = Path(temp) / "import.inkfont"
        shutil.copyfile(source, staged)
        progress("正在读取字体索引…")
        font = FontPackage(staged, verify_all=False)
        telemetry = {}
        legacy = not exchange_manifest(font.manifest)
        local = legacy and (capacity.local_package(font.manifest) or len(font.records) > exchange_codec.MAX_CANDIDATES)
        if convert_installed and (not legacy or local):
            raise ValueError("此字体无法整包转换为通用 v1")
        if local and approved_hash != font.manifest["content_hash"]:
            raise LocalFontConsent(len(font.records), font.manifest["content_hash"])
        stats = (verify_font(font, progress=progress, workers=workers, telemetry=telemetry)
                 if legacy else font.verify(progress=progress))
        original = None
        migration = None
        fallback = ""
        if legacy and not local:
            filename = font.manifest["package_id"] + ".inkfont"
            for existing in (root / "originals" / filename, root / filename):
                if existing.exists() and file_digest(existing) != file_digest(staged):
                    raise ValueError("字体库中存在同一包 ID 的不同文件；原文件保留，请先核查。")
            converted = Path(temp) / "exchange.inkfont"
            progress("正在另存统一字库 v1，并校验转换结果…")
            try:
                channels = tuple(exchange_codec.EXTENSIONS) if include_dynamics else ("math", "provenance")
                migration = exchange_codec.convert(staged, converted, extensions=channels, legacy_context=True)
                exchange = FontPackage(converted, verify_all=False)
            except (ValueError, KeyError, TypeError, ArithmeticError, BadZipFile, OSError) as error:
                if convert_installed:
                    raise
                migration = None
                fallback = f"；转换未完成，已使用验证通过的原版：{error}"
            else:
                if convert_installed:
                    if file_digest(source) != file_digest(staged):
                        raise ValueError("原字体在转换期间发生变化，请重新选择")
                    original = source
                else:
                    originals = root / "originals"
                    originals.mkdir(exist_ok=True)
                    original = originals / filename
                    try:
                        publish_copy(staged, original)
                    except OSError:
                        try:
                            originals.rmdir()
                        except OSError:
                            pass
                        raise
                font, staged = exchange, converted
        target = root / (font.manifest["package_id"] + ".inkfont")
        details = entry(font)
        progress("正在加入字体库…")
        if exchange_manifest(font.manifest):
            added_bytes = 0
            try:
                os.link(staged, target)
                added_bytes = target.stat().st_size
            except FileExistsError:
                existing = FontPackage(target, verify_all=False)
                if existing.manifest["content_hash"] != font.manifest["content_hash"]:
                    raise ValueError("统一字库发布身份冲突，已保留现有文件")
                if file_digest(target) != file_digest(staged):
                    existing.verify()
        else:
            publish_copy(staged, target)
    # Removing the staging hard link changes ctime on Windows. Stamp the final
    # file after cleanup so the UI does not immediately re-read its full index.
    if convert_installed:
        message = f"v1 字体已就绪。原包位置：{original}。新增 {added_bytes:,} 字节。"
    else:
        message = (f"字体已导入 · {(migration or stats)['characters']} 字，{(migration or stats)['candidates']} 份候选"
                   + ("；已转换为统一 v1，原版已保留" if original else "") + ("；已作为本机大容量字体使用" if local else "") + fallback)
    return {
        "path": str(target),
        "entry": (fingerprint(target), *details),
        "verification": (migration or stats), "source_verification": stats,
        "verification_runtime": telemetry,
        "local_capacity": local,
        "original_path": str(original) if original else None, "migration": migration,
        "message": message,
    }


def publish_font(root, *, writer, run, symbols, name, package_kind, groups, stamp, expected, progress, rules=None,
                 writer_links=None, local_capacity=False):
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
                       package_kind=package_kind, local_capacity=local_capacity, phase=phase, diagnostics=diagnostics, rules=rules,
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
