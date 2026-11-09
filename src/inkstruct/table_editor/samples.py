"""Read collector ZIPs without extraction; retain strokes and reproducible variants."""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .core import BUILTIN_GLYPHS, NumericGlyph, number_geometry


@dataclass(frozen=True)
class Sample:
    sample_id: str
    character: str
    glyph: NumericGlyph


@dataclass(frozen=True)
class SampleBank:
    path: Path
    sha256: str
    writer_id: str
    samples: dict[str, tuple[Sample, ...]]
    counts: dict[str, int]
    top_em: float
    bottom_em: float

    @property
    def summary(self):
        counts = [len(self.samples[c]) for c in "0123456789"]
        dot = (
            f"手写小数点 {len(self.samples['.'])} 份"
            if self.samples.get(".")
            else "小数点使用内置短线"
        )
        return f"{self.writer_id} · 数字 {sum(counts)} 份 · {dot}"

    def select(self, seed: int = 0):
        return SampleSelection(self, seed)


class SampleSelection(Mapping):
    """One instance per compilation, one deterministic choice per occurrence."""

    def __init__(self, bank, seed):
        self.bank, self.seed = bank, seed
        self.trace = []

    def __iter__(self):
        return iter("0123456789.")

    def __len__(self):
        return 11

    def __contains__(self, key):
        return key in "0123456789." and len(key) == 1

    def __getitem__(self, key):
        if key not in self:
            raise KeyError(key)
        if key == "." and not self.bank.samples.get("."):
            baseline = -self.bank.top_em / (self.bank.bottom_em - self.bank.top_em)
            dot = BUILTIN_GLYPHS["."]
            glyph = NumericGlyph(
                tuple(tuple((x, baseline + y - 1) for x, y in p) for p in dot.strokes),
                dot.advance,
            )
            sample_id = "builtin:decimal-point"
        else:
            pool = self.bank.samples[key]
            digest = hashlib.sha256(f"{self.seed}:{len(self.trace)}:{key}".encode()).digest()
            sample = pool[int.from_bytes(digest[:8], "big") % len(pool)]
            sample_id, glyph = sample.sample_id, sample.glyph
        self.trace.append({"character": key, "sample_id": sample_id})
        return glyph


def load_sample_zip(path: Path) -> SampleBank:
    path = Path(path).resolve()
    if path.stat().st_size > 50_000_000:
        raise ValueError("样本压缩包超过 50 MB")
    raw = path.read_bytes()
    records, counts, writers, ids = [], Counter(), set(), set()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [i for i in archive.infolist() if i.filename.endswith(".json")]
            if len(members) > 5000 or sum(i.file_size for i in members) > 100_000_000:
                raise ValueError("样本数量或解压体积超限")
            for member in members:
                if member.file_size > 1_000_000:
                    raise ValueError("单份样本超过 1 MB")
                d = json.loads(archive.read(member))
                if d["schema_version"] != "inkstruct_symbol_sample_v1":
                    raise ValueError("只支持符号采集器 v1 样本")
                ch, writer, sample_id = d["character"], d["writer_id"], d["sample_id"]
                if (
                    not all(isinstance(v, str) and v for v in (ch, writer, sample_id))
                    or len(ch) != 1
                ):
                    raise ValueError("样本标识无效")
                if sample_id in ids:
                    raise ValueError("样本 ID 重复")
                ids.add(sample_id)
                writers.add(writer)
                counts[ch] += 1
                if ch not in "0123456789.":
                    continue
                g = d["guides"]
                em, baseline, origin, cap = (
                    float(g[k]) for k in ("em_px", "baseline_y_px", "origin_x_px", "cap_height_em")
                )
                if (
                    not all(math.isfinite(v) for v in (em, baseline, origin, cap))
                    or em <= 0
                    or cap <= 0
                ):
                    raise ValueError("采集参考线无效")
                if d["capture"]["coordinate_space"] != "logical_px":
                    raise ValueError("只支持逻辑像素采集坐标")
                paths = tuple(
                    tuple(
                        ((float(p["x"]) - origin) / em, (float(p["y"]) - baseline) / em)
                        for p in stroke["points"]
                    )
                    for stroke in d["strokes"]
                )
                if not paths or sum(map(len, paths)) > 4096:
                    raise ValueError("笔画为空或点数超限")
                for stroke in paths:
                    if (
                        len(stroke) < 2
                        or len(set(stroke)) < 2
                        or not all(
                            math.isfinite(x) and math.isfinite(y) and abs(x) <= 10 and abs(y) <= 10
                            for x, y in stroke
                        )
                    ):
                        raise ValueError("样本存在无效或零长笔画")
                records.append((ch, sample_id, paths, cap))
        if len(writers) != 1:
            raise ValueError("每次需导入一位书写者的样本")
        missing = [c for c in "0123456789" if not counts[c]]
        if missing:
            raise ValueError("缺少数字样本：" + ", ".join(missing))
        # One vertical frame and isotropic scale for the whole bank, preserving
        # baseline offsets and relative heights. No per-glyph height stretching.
        top = min(-cap for _, _, _, cap in records)
        top = min(top, min(y for _, _, paths, _ in records for stroke in paths for _, y in stroke))
        bottom = max(
            0.0, max(y for _, _, paths, _ in records for stroke in paths for _, y in stroke)
        )
        height = bottom - top
        samples = {c: [] for c in "0123456789." if counts[c]}
        for ch, sample_id, paths, _ in records:
            left = min(x for stroke in paths for x, _ in stroke)
            right = max(x for stroke in paths for x, _ in stroke)
            width = (right - left) / height
            advance = max(0.2 if ch == "." else 0.45, width + 0.16)
            bearing = (advance - width - 0.16) / 2
            glyph = NumericGlyph(
                tuple(
                    tuple(((x - left) / height + bearing, (y - top) / height) for x, y in stroke)
                    for stroke in paths
                ),
                advance,
            )
            number_geometry(ch, {ch: glyph})
            samples[ch].append(Sample(sample_id, ch, glyph))
        return SampleBank(
            path,
            hashlib.sha256(raw).hexdigest(),
            next(iter(writers)),
            {c: tuple(sorted(pool, key=lambda s: s.sample_id)) for c, pool in samples.items()},
            dict(counts),
            top,
            bottom,
        )
    except (
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        zipfile.BadZipFile,
        RuntimeError,
    ) as error:
        raise ValueError(f"无法读取符号采集样本：{error}") from error
