"""Read generation batches and their saved donor evidence without altering either."""

from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from .assets.glyph_provider import is_han
from .fonts.importer import _read, generated_records
from .fonts.publication import batch_info
from .generation_workflow import GenerationWorkflow
from .geometry import bbox
from .samples import iter_index, load_raw_sample, sha256_file


RECORD_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError)


def batch_history(root):
    root = Path(root)
    result = []
    for folder in root.glob("*"):
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in (folder, *folder.glob("*")):
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                if (path / "v63-run.json").is_file():
                    data = _read(path / "v63-run.json")
                    writers = [data["writer"]]
                elif (path / "protocol.json").is_file():
                    writers = _read(path / "protocol.json").get("writers", ())
                elif (path / "manifest.json").is_file():
                    writers = [_read(path / "manifest.json")["writer_id"]]
                else:
                    first = next((path / "trajectories").glob("U+*.json"), None)
                    writers = [_read(first)["writer_id"]] if first else []
                for writer in writers:
                    GenerationWorkflow.validate_writer(writer)
                    result.append({**batch_info(path, writer), "writer": writer})
            except RECORD_ERRORS:
                continue
    return sorted(result, key=lambda info: (info["date"], info["path"].name), reverse=True)


@dataclass(frozen=True)
class StrokeSource:
    slots: tuple
    points: tuple
    kind: str
    character: str = ""
    sample: str = ""
    digest: str = ""
    standard_id: str = ""
    raw_order: int | None = None

    @property
    def key(self):
        return self.character, self.digest or self.sample


def xy(points):
    return tuple((point["x"], point["y"]) for point in points)


def source_kind(kind):
    if kind in {"reference", "explicit_gap"}:
        return "标准骨架"
    if kind in {"author_group", "author_complete_component", "author_hybrid_retained"}:
        return "部件复用"
    if kind in {"author_single_stroke", "author_hybrid_key"}:
        return "单笔拼接"
    return "已记录来源" if kind else "来源未记录"


def inspect_candidates(batch, character):
    for glyph, row, payload, protocol in generated_records(batch["path"], batch["writer"], character=character):
        data = protocol or {}
        version = str(data.get("version") or glyph.get("generator") or "未记录")
        sources = payload.get("stroke_sources") or (row or {}).get("stroke_sources") or []
        if "segments" in glyph:
            base = {r.get("standard_id"): r for r in payload.get("base_stroke_sources", ())}
            strokes = []
            for segment in glyph["segments"]:
                slots = tuple(segment["standard_slots"])
                origin = base.get(slots[0], {})
                digest = segment.get("source_sha256", "")
                character_from = segment.get("source_character", "")
                kind = segment["kind"]
                if (kind != "author_split" or not digest or origin.get("source_sha256") != digest
                        or origin.get("character") != character_from):
                    origin = {}
                label = ("整字复用" if glyph.get("method") == "same_character"
                         else source_kind(segment.get("source_kind") or kind))
                strokes.append(StrokeSource(slots, xy(segment["points"]), label, character_from,
                                            origin.get("sample_id", ""), digest,
                                            origin.get("source_stroke_id", ""), segment.get("source_raw_order")))
            yield version, strokes, data.get("profile") or {}
        else:
            by_order = {r.get("order"): r for r in sources}
            provenance = payload.get("provenance") or {}
            strokes = []
            for order, stroke in enumerate(glyph["strokes"], 1):
                origin = by_order.get(order) or (
                    provenance.get(str(order - 1), {}) if isinstance(provenance, dict) else {})
                slots = (stroke.get("standard_stroke_id") or str(order),)
                strokes.append(StrokeSource(slots, xy(stroke["points"]), source_kind(origin.get("kind")),
                                            origin.get("character", ""), origin.get("sample_id", ""),
                                            origin.get("source_sha256", ""), origin.get("source_stroke_id", "")))
            yield version, strokes, data.get("profile") or {}


@dataclass(frozen=True)
class Recording:
    strokes: tuple = ()
    status: str = "未找到原录制，显示批次保存的来源"
    canvas_size: tuple[float, float] | None = None

    def framed_strokes(self, character):
        if not self.canvas_size:
            return ()
        width, height = self.canvas_size
        side = max(width, height)
        center_x, center_y = width / 2, height / 2
        if is_han(character) and any(self.strokes):
            left, top, right, bottom = bbox([point for stroke in self.strokes for point in stroke])
            # Fit the whole recording with padding. Keep a minimum frame tied to
            # the capture height/short side so even a small Han mark stays small.
            side = max(0.6 * min(width, height), 1.25 * max(right - left, bottom - top))
            center_x, center_y = (left + right) / 2, (top + bottom) / 2
        return tuple(tuple((0.5 + (x - center_x) / side, 0.5 + (y - center_y) / side)
                           for x, y in stroke) for stroke in self.strokes)


class SourceArchive:
    def __init__(self, writer, profile, imports, capture):
        self.writer = writer
        self.profile = profile
        self.imports = Path(imports)
        self.capture = Path(capture)

    @cached_property
    def trajectories(self):
        from .profile import load_profile

        path, digest = self.profile.get("path"), self.profile.get("sha256")
        if path and digest:
            try:
                path = Path(path)
                if sha256_file(path) == digest:
                    profile = load_profile(path)
                    if profile.writer_id == self.writer:
                        return profile.source_trajectories
            except RECORD_ERRORS:
                pass
        return {}

    @cached_property
    def samples(self):
        digest = self.profile.get("index_sha256")
        if digest:
            for path in self.imports.glob(f"*/{self.writer}/index.jsonl"):
                try:
                    if sha256_file(path) == digest:
                        return {s.source_sha256: s for s in iter_index(path) if s.writer_id == self.writer}
                except RECORD_ERRORS:
                    continue
        return {}

    def recording(self, character, digest):
        saved = self.samples.get(digest)
        if saved and saved.character != character:
            saved = None
        if len(character) != 1:
            return None, False
        folder = self.capture / "samples" / self.writer / f"U+{ord(character):04X}"
        paths = ([Path(saved.source_path)] if saved else []) + list(folder.glob("*.json"))
        for path in paths:
            try:
                if sha256_file(path) == digest:
                    original = load_raw_sample(path, expected_writer=self.writer)
                    if original.source_sha256 == digest and original.character == character:
                        return original, True
            except RECORD_ERRORS:
                continue
        return saved, False

    def resolve(self, strokes):
        recordings = {}
        resolved = []
        for stroke in strokes:
            if not stroke.digest or not stroke.character:
                resolved.append(stroke)
                continue
            if stroke.key not in recordings:
                recordings[stroke.key] = self.recording(stroke.character, stroke.digest)
            sample, original = recordings[stroke.key]
            sample_id = stroke.sample or (sample.sample_id if sample else "")
            order = stroke.raw_order
            if order is None and stroke.standard_id and sample_id:
                trajectory = self.trajectories.get(sample_id)
                if (trajectory and trajectory.source_sha256 == stroke.digest
                        and trajectory.character == stroke.character):
                    order = next((s.user_order for s in trajectory.strokes
                                  if s.standard_stroke_id == stroke.standard_id), None)
            resolved.append(replace(stroke, sample=sample_id, raw_order=order))
        return resolved, {
            key: Recording(tuple(tuple((p.x, p.y) for p in stroke.points) for stroke in sample.strokes),
                           "原录制" if original else "原文件缺失，显示导入索引保留的笔迹",
                           (sample.canvas_width, sample.canvas_height))
            if sample else Recording()
            for key, (sample, original) in recordings.items()
        }


def character_query(text):
    text = text.strip()
    if text.upper().startswith("U+"):
        try:
            return chr(int(text[2:], 16))
        except (ValueError, OverflowError):
            pass
    return text
