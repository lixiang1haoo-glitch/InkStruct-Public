"""Application adapter for InkStruct / OpenInk exchange v1. Coordinates use the baseline as origin."""
from pathlib import Path
from uuid import UUID, uuid5
from zipfile import ZipFile

from ..document.cancellation import check_cancel
from . import exchange_codec as codec
from .core import encoded, latin, resolved_candidate, semantic_hash, sha, trajectory_hashes


def identity(manifest):
    codec.validate_font_identity(manifest)
    font_id = manifest["font_id"]
    members = manifest["members"]
    core_paths = (p for p in members if p == "index.json" or p.startswith("glyphs/"))
    content_hash = sha(encoded(manifest))
    release = str(uuid5(UUID(font_id), content_hash))
    return dict(font_id=font_id, core_hash=codec.core_hash(manifest, core_paths),
                release_id=release, package_id=release, content_hash=content_hash)


class ExchangeFont:
    def __init__(self, path):
        self.path = Path(path)
        stat = self.path.stat()
        self.fingerprint = stat.st_size, stat.st_mtime_ns
        codec.require(stat.st_size <= codec.MAX_ARCHIVE, "v1 压缩包超限")
        with ZipFile(path) as archive:
            checked = codec.CheckedArchive(archive)
            manifest = checked.manifest
            codec.require(manifest.get("format") == "inkfont" and type(manifest.get("format_version")) is int
                          and manifest["format_version"] == 1, "不支持的统一字库版本")
            self.members = checked.members
            self.index = checked.json("index.json")
            ids = set()
            self.records, self.pools, self.provenance = [], {}, {}
            for char, cid, member in codec.indexed_candidates(self.index, self.members):
                ids.add(cid)
                record = dict(character=char, candidate_id=cid, file=member, enabled=True)
                self.records.append(record)
                self.pools.setdefault(char, []).append(record)
            source = self._metadata(checked, "provenance", ids)
            math_axes = self._metadata(checked, "math", ids)
            legacy = (checked.json("extensions/inkstruct-release-v1.json")
                      if "extensions/inkstruct-release-v1.json" in self.members else {})
        ids_map = identity(manifest)
        reference = legacy.get("original_release", {}) if isinstance(legacy, dict) else {}
        writer = reference.get("writer_alias") if isinstance(reference, dict) else None
        self.manifest = dict(manifest, **ids_map, package_kind="exchange",
                             writer_alias=writer if isinstance(writer, str) and writer else "未注明",
                             font_version="1")
        self.identity = {k: self.manifest[k] for k in ("font_id", "release_id", "core_hash", "writer_alias")}
        self.identity["exchange_format"] = 1
        for record in self.records:
            cid = record["candidate_id"]
            info = source.get(cid, {})
            default = "unspecified" if latin(record["character"]) else "not_applicable"
            record["letter_style"] = info.get("letter_style", default)
            summary = dict(source_kind=info.get("source_kind", "unknown"), protocol_status="valid",
                           author_source_status="unknown", review_status="unreviewed")
            if info:
                summary["exchange_provenance"] = info
            if cid in math_axes:
                summary["exchange_math_y"] = math_axes[cid]["math_axis_em"]
            self.provenance[cid] = summary

    @staticmethod
    def _metadata(checked, kind, ids):
        path = codec.EXTENSIONS[kind]
        if path not in checked.members:
            return {}
        data = checked.json(path)
        codec.verify_extension(kind, data, checked, dict.fromkeys(ids))
        return data["entries"]

    def verify(self, *, progress=None):
        if progress:
            progress("正在完整校验统一字库及可选扩展…")
        return codec.verify(self.path)

    def load_glyph(self, archive, record, reuse=None):
        cid, char, path = record["candidate_id"], record["character"], record["file"]
        raw = archive.read(path)
        spec = self.members[path]
        codec.require(len(raw) == spec["bytes"] and sha(raw) == spec["sha256"], "字形轨迹摘要不符")
        data = codec.decode(raw)
        codec.trajectory_shape(data)
        xy = data["strokes"]
        xs = [x for stroke in xy for x, _ in stroke]
        ys = [y for stroke in xy for _, y in stroke]
        metrics = dict(baseline=0., advance=max(.12, max(xs) - min(xs) + .08),
                       ascent=max(.88, -min(ys)), descent=max(.12, max(ys)))
        trajectory = dict(schema_version="inkfont_trajectory_v1", coordinate_space="em-y-down-baseline-zero",
                          character=char, strokes=[
                              dict(order=i, stroke_ref=f"stroke-{i}",
                                   dynamic_origin=dict(pressure="absent", time="absent", pen_state="absent"),
                                   points=[dict(x=x, y=y) for x, y in stroke])
                              for i, stroke in enumerate(xy, 1)])
        summary = dict(self.provenance[cid], unknown_strokes=list(range(1, len(xy) + 1)),
                       author_strokes=[], reference_strokes=[], gaps=[], warnings=[])
        full_record = dict(record, **trajectory_hashes(trajectory), source_summary_hash=semantic_hash(summary))
        full_record["metrics_id"] = semantic_hash(metrics)
        return resolved_candidate(full_record, trajectory, metrics, summary, self.identity, _reuse=reuse)

    def glyphs(self, characters=None, *, reuse=(), cancelled=None):
        stat = self.path.stat()
        if self.fingerprint != (stat.st_size, stat.st_mtime_ns):
            raise ValueError("字体文件已变化，请重新导入")
        prior = {g.sample_id: g for g in reuse}
        with ZipFile(self.path) as archive:
            for char in sorted(self.pools if characters is None else set(characters)):
                for record in self.pools.get(char, ()):
                    check_cancel(cancelled)
                    yield self.load_glyph(archive, record, prior.get(record["candidate_id"]))
