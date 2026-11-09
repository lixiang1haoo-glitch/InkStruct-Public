from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from ..document.schema import digest
from ..schemas import GeneratedGlyph

PROVIDER_VERSION = "generated-trajectory-v1/em-baseline-0.88/constant-brush-v1"


def is_han(text: str) -> bool:
    # Generated standalone radicals use the same normalized Chinese em contract.
    # Some are full-library targets even though Unicode names them as symbols.
    return len(text) == 1 and unicodedata.name(text, "").startswith(
        ("CJK UNIFIED IDEOGRAPH", "CJK RADICAL", "KANGXI RADICAL")
    )


@dataclass(frozen=True)
class GlyphMetrics:
    """Unscaled em metrics; baseline is measured from the asset's top origin."""

    advance: float = 1.0
    baseline: float = 0.88
    ascent: float = 0.88
    descent: float = 0.12

    def __post_init__(self) -> None:
        if (
            not all(math.isfinite(v) for v in asdict(self).values())
            or self.advance <= 0
            or min(self.ascent, self.descent) < 0
            or self.ascent + self.descent <= 0
        ):
            raise ValueError("Invalid glyph metrics")


@dataclass(frozen=True)
class AssetPoint:
    x: float
    y: float
    t_ms: int
    pressure: float
    pen_state: str


@dataclass(frozen=True)
class GlyphAsset:
    asset_id: str
    character: str
    original_json: bytes
    strokes: tuple[tuple[AssetPoint, ...], ...]
    metrics: GlyphMetrics
    centerline_bounds: tuple[float, float, float, float]
    provider_version: str = PROVIDER_VERSION


def adapt_glyph(
    value: dict | GeneratedGlyph,
    *,
    metrics: GlyphMetrics | None = None,
    original_json: bytes | None = None,
) -> GlyphAsset:
    """Freeze a copy; never fit, resample, reorder or remove up/end endpoints."""
    if isinstance(value, GeneratedGlyph):
        value = asdict(value)
    if not isinstance(value, dict) or value.get("schema_version") != "personal_trajectory_v1":
        raise ValueError("Unsupported trajectory schema")
    character = value["character"]
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError("A generated asset must cover exactly one Unicode scalar")
    if metrics is None and not is_han(character):
        raise ValueError("Non-Han assets require explicit calibrated em metrics")
    metrics = metrics or GlyphMetrics()
    strokes = []
    previous_time = 0
    for order, stroke in enumerate(value["strokes"], 1):
        if stroke["order"] != order or not stroke["points"]:
            raise ValueError("Invalid stroke order or empty stroke")
        points = []
        for point in stroke["points"]:
            p = AssetPoint(**{k: point[k] for k in ("x", "y", "t_ms", "pressure", "pen_state")})
            if (
                not all(
                    isinstance(v, (int, float)) and math.isfinite(v)
                    for v in (p.x, p.y, p.t_ms, p.pressure)
                )
                or not 0 <= p.pressure <= 1
                or not (-1e-6 <= p.x <= 1 + 1e-6 and -1e-6 <= p.y <= 1 + 1e-6)
                or not isinstance(p.t_ms, int)
                or p.t_ms < previous_time
                or p.pen_state not in ("down", "up", "end")
            ):
                raise ValueError("Invalid trajectory coordinates, timing, pressure or pen state")
            previous_time = p.t_ms
            points.append(p)
        strokes.append(tuple(points))
    if not strokes:
        raise ValueError("Empty glyph geometry")
    xs = [p.x for stroke in strokes for p in stroke]
    ys = [p.y for stroke in strokes for p in stroke]
    raw = (
        original_json
        or json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    )
    asset_id = sha256(raw).hexdigest()
    return GlyphAsset(
        asset_id, character, raw, tuple(strokes), metrics, (min(xs), min(ys), max(xs), max(ys))
    )


class GlyphProvider:
    """An immutable, eagerly resolved resource set for a single layout request."""

    def __init__(self, assets: Mapping[str, GlyphAsset], failures: Mapping[str, str] | None = None):
        self.assets = MappingProxyType(dict(assets))
        self.failures = MappingProxyType(dict(failures or {}))
        self.resource_key = digest(
            {
                "provider": PROVIDER_VERSION,
                "assets": {c: (a.asset_id, asdict(a.metrics)) for c, a in self.assets.items()},
                "failures": dict(self.failures),
            }
        )

    @classmethod
    def from_run(
        cls,
        run: Path,
        source: str,
        calibrations: Mapping[str, GlyphMetrics] | None = None,
        *,
        cache=None,
    ) -> GlyphProvider:
        assets, failures = {}, {}
        root = run / "trajectories"
        if not root.is_dir():
            raise ValueError(f"Missing trajectory directory: {root}")
        for char in sorted(set(source)):
            if char in " \t\r\n\u3000\u00a0":
                continue
            path = root / f"U+{ord(char):04X}.json"
            if not path.exists():
                continue
            try:
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("Trajectory exceeds the 16 MiB asset limit")
                raw = path.read_bytes()
                metrics = (calibrations or {}).get(char)
                key = (
                    "generated",
                    PROVIDER_VERSION,
                    sha256(raw).hexdigest(),
                    digest(asdict(metrics)) if metrics is not None else None,
                )
                asset = cache.get(key) if cache is not None else None
                if asset is None:
                    asset = adapt_glyph(json.loads(raw), metrics=metrics, original_json=raw)
                    if cache is not None:
                        cache.put((key,), asset, len(raw) + sum(map(len, asset.strokes)) * 192)
                if asset.character != char:
                    raise ValueError("Asset character does not match filename")
                assets[char] = asset
            except (ValueError, KeyError, TypeError, OSError) as error:
                failures[char] = str(error)
        return cls(assets, failures)
