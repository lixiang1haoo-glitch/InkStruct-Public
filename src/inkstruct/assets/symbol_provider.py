"""Immutable symbol specimens in a fixed em frame, without per-bank rescaling."""

from __future__ import annotations

import io
import json
import math
import zipfile
from dataclasses import asdict, dataclass
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from ..document.schema import digest
from ..plotter.schema import PathPoints
from .glyph_provider import GlyphAsset, GlyphMetrics


@dataclass(frozen=True)
class SymbolProfile:
    """Guide-based initial calibration; adding specimens never changes this frame."""

    baseline: float = 0.88
    ascent: float = 0.88
    descent: float = 0.25
    math_axis: float = 0.25
    advance_margin: float = 0.08
    minimum_advance: float = 0.12
    version: str = "symbol-guide-em-v1-unreviewed"

    def __post_init__(self):
        if any(not math.isfinite(v) or v < 0 for k, v in asdict(self).items() if k != "version"):
            raise ValueError("Invalid symbol profile")
        if self.minimum_advance <= 0 or self.ascent + self.descent <= 0:
            raise ValueError("Invalid symbol profile dimensions")

    @property
    def key(self):
        return digest(asdict(self))


DEFAULT_SYMBOL_PROFILE = SymbolProfile()


@dataclass(frozen=True)
class ResolvedGlyph:
    asset_id: str
    character: str
    sample_id: str
    writer_id: str
    strokes: tuple[PathPoints, ...]
    metrics: GlyphMetrics
    metrics_key: str
    original_json: bytes
    provider_version: str

    @cached_property
    def font_core(self):
        return json.loads(self.original_json) if self.provider_version == "inkfont-core-v1" else None

    @property
    def font_metadata(self):
        if "_font_metadata" in self.__dict__:
            return self._font_metadata
        return self.font_core

    @property
    def math_axis_em(self):
        """Read recorded metadata, never infer an axis from shape or defaults."""
        if self.font_core is not None:
            summary = self.font_core['summary']
            if summary.get('source_kind') == 'composed':
                return summary.get('symbol_construction', {}).get('math_axis_em')
            return summary.get('capture_guides', {}).get('math_axis_em')
        return json.loads(self.original_json).get('guides', {}).get('math_axis_em')

    @property
    def machine_capability(self):
        return (
            "centerline"
            if all(len(set(stroke)) >= 2 for stroke in self.strokes)
            else "point-adaptation-required"
        )

    @property
    def layout_bounds(self):
        metadata = self.font_metadata
        frame = metadata["summary"].get("optical_layout_frame") if metadata else None
        return tuple(frame["bounds"]) if frame else self.bounds

    @property
    def layout_metrics(self):
        metadata = self.font_metadata
        frame = metadata["summary"].get("optical_layout_frame") if metadata else None
        return GlyphMetrics(**frame["metrics"]) if frame else self.metrics

    @cached_property
    def bounds(self):
        points = [p for stroke in self.strokes for p in stroke]
        return (
            min(x for x, _ in points),
            min(y for _, y in points),
            max(x for x, _ in points),
            max(y for _, y in points),
        )

    @cached_property
    def retained_bytes(self):
        # Immutable source bytes and tuple geometry dominate retained storage.
        # Count points conservatively without visiting every coordinate object.
        return 2048 + len(self.original_json) + sum(256 + len(s) * 128 for s in self.strokes)


def from_generated(asset: GlyphAsset) -> ResolvedGlyph:
    return ResolvedGlyph(
        asset.asset_id,
        asset.character,
        asset.asset_id,
        json.loads(asset.original_json).get("writer_id", "unknown-generated"),
        tuple(tuple((p.x, p.y) for p in stroke) for stroke in asset.strokes),
        asset.metrics,
        digest(asdict(asset.metrics)),
        asset.original_json,
        asset.provider_version,
    )


def adapt_symbol(raw: bytes, profile: SymbolProfile = DEFAULT_SYMBOL_PROFILE) -> ResolvedGlyph:
    value = json.loads(raw)
    if value["schema_version"] != "inkstruct_symbol_sample_v1":
        raise ValueError("Unsupported symbol specimen schema")
    char, sid, writer = (value[k] for k in ("character", "sample_id", "writer_id"))
    if any(not isinstance(v, str) or not v for v in (char, sid, writer)) or len(char) != 1:
        raise ValueError("Invalid symbol identity")
    char.encode("utf-8")
    if value["capture"]["coordinate_space"] != "logical_px":
        raise ValueError("Symbol coordinates must use logical pixels")
    em, origin, baseline = (
        float(value["guides"][k]) for k in ("em_px", "origin_x_px", "baseline_y_px")
    )
    if not all(math.isfinite(v) for v in (em, origin, baseline)) or em <= 0:
        raise ValueError("Invalid symbol guides")
    strokes = []
    previous_time = -1
    for stroke in value["strokes"]:
        points = []
        for point in stroke["points"]:
            x = (float(point["x"]) - origin) / em
            y = profile.baseline + (float(point["y"]) - baseline) / em
            if not all(math.isfinite(v) and abs(v) <= 10 for v in (x, y)):
                raise ValueError("Invalid symbol coordinates")
            if "pressure" in point and not (
                math.isfinite(point["pressure"]) and 0 <= point["pressure"] <= 1
            ):
                raise ValueError("Invalid symbol pressure")
            if "t_ms" in point:
                timestamp = point["t_ms"]
                if (
                    not isinstance(timestamp, (int, float))
                    or not math.isfinite(timestamp)
                    or timestamp < 0
                    or timestamp < previous_time
                ):
                    raise ValueError("Invalid symbol sample time")
                previous_time = timestamp
            points.append((x, y))
        if not points:
            raise ValueError("Empty symbol stroke")
        strokes.append(tuple(points))
    if not strokes or sum(map(len, strokes)) > 4096:
        raise ValueError("Invalid symbol point count")
    # Retain single points as source evidence; machine capability checks are separate.
    right = max(x for stroke in strokes for x, _ in stroke)
    advance = max(profile.minimum_advance, right + profile.advance_margin)
    metrics = GlyphMetrics(advance, profile.baseline, profile.ascent, profile.descent)
    return ResolvedGlyph(
        sha256(raw).hexdigest(),
        char,
        sid,
        writer,
        tuple(strokes),
        metrics,
        profile.key,
        raw,
        "symbol-sample-v1/fixed-guide-em",
    )


class SymbolProvider:
    def __init__(self, glyphs, *, archive_hash="", profile=DEFAULT_SYMBOL_PROFILE):
        pools = {}
        ids, writers = set(), set()
        for glyph in glyphs:
            if glyph.sample_id in ids:
                raise ValueError("Duplicate symbol sample ID")
            if glyph.metrics_key != profile.key:
                raise ValueError("Symbol sample/profile mismatch")
            ids.add(glyph.sample_id)
            writers.add(glyph.writer_id)
            pools.setdefault(glyph.character, []).append(glyph)
        if len(writers) > 1:
            raise ValueError("Import one writer per symbol provider")
        self.pools = MappingProxyType(
            {c: tuple(sorted(v, key=lambda g: g.sample_id)) for c, v in pools.items()}
        )
        self.archive_hash, self.profile = archive_hash, profile
        self.resource_key = digest(
            {
                "profile": profile.key,
                "assets": {c: [g.asset_id for g in v] for c, v in self.pools.items()},
            }
        )

    @classmethod
    def from_zip(cls, path: Path, *, profile=DEFAULT_SYMBOL_PROFILE, cache=None):
        path = Path(path)
        if path.stat().st_size > 50_000_000:
            raise ValueError("Symbol archive exceeds 50 MB")
        raw = path.read_bytes()
        archive_hash = sha256(raw).hexdigest()
        key = ("symbol-sample-v1/fixed-guide-em", archive_hash, profile.key)
        cached = cache.get(key) if cache is not None else None
        if cached is not None:
            return cls(cached, archive_hash=archive_hash, profile=profile)
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = [m for m in archive.infolist() if m.filename.endswith(".json")]
                if (
                    len(members) > 5000
                    or sum(m.file_size for m in members) > 100_000_000
                    or any(m.file_size > 1_000_000 for m in members)
                ):
                    raise ValueError("Symbol archive exceeds resource limits")
                glyphs = [adapt_symbol(archive.read(m), profile) for m in members]
            if not glyphs:
                raise ValueError("No symbol specimens in archive")
            result = cls(glyphs, archive_hash=archive_hash, profile=profile)
            if cache is not None:
                cache.put(
                    (key,),
                    tuple(glyphs),
                    sum(len(g.original_json) + sum(map(len, g.strokes)) * 128 for g in glyphs),
                )
            return result
        except (KeyError, TypeError, zipfile.BadZipFile, RuntimeError, OverflowError) as error:
            raise ValueError(f"Cannot read symbol archive: {error}") from error
