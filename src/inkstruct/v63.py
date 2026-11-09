"""Isolated v6.3 workflow. The existing v6.2 engine supplies the base layout."""

from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
import gzip
import json
from pathlib import Path

import numpy as np

from .generation_workflow import prepare_generation, read, write
from .profile import build_profile
from .samples import scan_samples, sha256_file, write_sample_index
from .structure_corrections import CorrectedStructureRepository
from .trajectory_experiment import crossing_pairs
from .v61_candidate_expansion import correspondence
from .v61_contacts import BRUSH_WIDTH, segment_clearance
from .v63_alignment import align_groups


ARCHIVE = "inkstruct_v63_group_archive_v1"
RUN = "inkstruct_v63_grouped_run_v1"
GLYPH = "inkstruct_v63_grouped_glyph_v1"


def slots(graph, node):
    owned = set(node.stroke_ids)
    return tuple(s.order-1 for s in graph.strokes if s.stroke_id in owned)


def top_parts(graph):
    root = next((n for n in graph.components if n.path == "root"), None)
    if root is None or root.layout not in {"⿰", "⿱"}:
        return ()
    children = tuple(n for n in graph.components if n.parent_id == root.component_id)
    parts = [slots(graph, n) for n in children]
    if len(parts) != 2 or not all(parts) or sorted(i for part in parts for i in part) != list(range(len(graph.strokes))):
        return ()
    return children


def key(graph, node):
    layout = next(n.layout for n in graph.components if n.path == "root")
    return [layout, node.role, node.canonical, node.glyph_variant,
            [graph.strokes[i].stroke_type for i in slots(graph, node)]]


def extract_unit(sample, graph, path, confirmed, observed, wanted):
    if not wanted or wanted != tuple(range(wanted[0], wanted[-1]+1)):
        return None
    owned = set(wanted)
    edges = [e for e in path if owned.intersection(e.slots)]
    if any(e not in confirmed or not set(e.slots) <= owned for e in edges):
        return None
    if tuple(i for e in edges for i in e.slots) != wanted:
        return None
    if not any(len(e.slots) > 1 for e in edges):
        return None
    order = [e.raw[0] for e in edges]
    if order != list(range(order[0], order[-1]+1)):
        return None
    if len(wanted) == len(graph.strokes) and order != list(range(len(sample.strokes))):
        return None
    result = []
    for edge in edges:
        physical = edge.raw[0]
        raw = sample.strokes[physical].points
        geometry = observed[physical]
        if np.any(geometry < 0) or np.any(geometry > 1):
            return None
        result.append({
            "slots": [graph.strokes[i].stroke_id for i in edge.slots],
            "raw_order": physical+1,
            "points": [{**asdict(p), "x": float(x), "y": float(y)}
                       for p, (x, y) in zip(raw, geometry, strict=True)],
            "coverage": list(edge.coverage), "margin": confirmed[edge],
        })
    return result


def sample_units(sample, graph, *, audit=None):
    observed, path, confirmed = align_groups(sample, graph)
    units = []
    whole = extract_unit(sample, graph, path, confirmed, observed, tuple(range(len(graph.strokes))))
    if whole:
        units.append(("whole", None, whole))
    for part in top_parts(graph):
        local = extract_unit(sample, graph, path, confirmed, observed, slots(graph, part))
        if local:
            units.append((part.path, key(graph, part), local))
    if audit is not None:
        audit.update(
            missing=[i+1 for e in path if not e.raw for i in e.slots],
            unmatched_physical=[i+1 for e in path if not e.slots for i in e.raw],
            weak=[i+1 for e in path if e.raw and not e.trusted for i in e.slots],
            ambiguous=[i+1 for e in path if e.trusted and e not in confirmed for i in e.slots],
            admitted=[part for part, _, _ in units],
        )
    return units


def make_archive(source, writer, repo, output):
    from .generation_workflow import GenerationWorkflow
    GenerationWorkflow.validate_writer(writer)
    if output.exists() or output.resolve().is_relative_to(source.resolve()):
        raise ValueError("请选择新的隔离档案目录，放在原始样本目录之外")
    samples, rejected, foreign = scan_samples(source, writer)
    if foreign:
        raise ValueError("样本目录包含其他书写者")
    if not samples:
        raise ValueError("没有可导入的原始笔迹")
    output.mkdir(parents=True)
    report = write_sample_index(source, writer, output / "index", samples, rejected)
    profile, profile_path = build_profile(writer, Path(report["index"]), repo, output / "split",
                                          retain_source_trajectories=True)
    units, reviewed = [], []
    for sample in samples:
        if sample.sample_id in profile.source_trajectories:
            continue
        audit = {}
        try:
            found = sample_units(sample, repo.get(sample.character), audit=audit)
        except (KeyError, ValueError) as error:
            reviewed.append({"sample": sample.sample_id, "character": sample.character, "reason": str(error)})
            continue
        units.extend({"character": sample.character, "sample": sample.sample_id,
                      "source_sha256": sample.source_sha256, "path": part, "key": identity,
                      "strokes": strokes}
                     for part, identity, strokes in found)
        if not any(part == "whole" for part, _, _ in found):
            reviewed.append({"sample": sample.sample_id, "character": sample.character,
                             "reason": "仅局部准入" if found else "连写组未达到独立准入条件", **audit})
    data = {
        "schema_version": ARCHIVE, "writer": writer, "structure_sha256": repo.content_sha256(),
        "split_profile": str(profile_path.relative_to(output.resolve())),
        "split_sha256": sha256_file(profile_path),
        "units": units, "imported": len(samples), "split_donors": len(profile.source_trajectories),
        "review": reviewed, "import_rejected": len(rejected),
    }
    write(output / "archive.json", data)
    return {k: data[k] for k in ("imported", "split_donors", "review", "import_rejected")} | {
        "connected_whole": sum(u["path"] == "whole" for u in units),
        "connected_parts": sum(u["path"] != "whole" for u in units),
    }


def fit_component(source, target):
    src = np.concatenate(source)
    dst = np.concatenate(target)
    a, b = src.min(axis=0), src.max(axis=0)
    c, d = dst.min(axis=0), dst.max(axis=0)
    if min(min(b-a), min(d-c)) <= 1e-8:
        raise ValueError("部件范围不足")
    ratios = (d-c)/(b-a)
    if max(ratios)/min(ratios) > 1.65:
        raise ValueError("目标部件比例差异过大")
    return [(trace-(a+b)/2)*min(ratios)+(c+d)/2 for trace in source]


def new_relationships(placed, outside, original):
    """Reject a new centerline crossing or a new brush contact with other ink."""
    for neighbor in outside:
        for trace, expected in zip(placed, original, strict=True):
            if crossing_pairs([trace, neighbor]) and not any(
                crossing_pairs([old, neighbor]) for old in expected
            ):
                return True
            if (segment_clearance(trace, neighbor) <= BRUSH_WIDTH
                    and min(segment_clearance(old, neighbor) for old in expected) > BRUSH_WIDTH):
                return True
    return False


def mapped_segments(unit, mapping, placed=None):
    result = []
    for i, stroke in enumerate(unit["strokes"]):
        points = stroke["points"]
        if placed is not None:
            points = [{**p, "x": float(x), "y": float(y)}
                      for p, (x, y) in zip(points, placed[i], strict=True)]
        result.append({"standard_slots": [mapping[s] for s in stroke["slots"]], "points": points,
                       "kind": "author_group", "source_character": unit["character"],
                       "source_sha256": unit["source_sha256"], "source_raw_order": stroke["raw_order"]})
    return result


def physical_points(segments):
    """Retain within-segment timing and pressure. Set lift state per physical stroke."""
    cursor = 0
    result = []
    for i, segment in enumerate(segments):
        raw = segment["points"]
        points = []
        for j, p in enumerate(raw):
            state = "down" if j < len(raw)-1 else ("end" if i == len(segments)-1 else "up")
            points.append({k: p[k] for k in ("x", "y", "pressure")} |
                          {"t_ms": cursor+p["t_ms"]-raw[0]["t_ms"], "pen_state": state})
        cursor = points[-1]["t_ms"] + 60
        result.append({**segment, "points": points})
    return result


def candidates_for(target_graph, corrected, base_segments, units, source_repo, *, same_character):
    target_ids = [s.stroke_id for s in target_graph.strokes]
    candidates = []
    if same_character:
        for u in units:
            if u["path"] == "whole" and u["character"] == target_graph.character:
                identity = {i: i for i in target_ids}
                candidates.append(("same_character", mapped_segments(u, identity)))
    original = [np.array([(p["x"], p["y"]) for p in seg["points"]]) for seg in base_segments]
    originals_by_id = dict(zip(target_ids, original, strict=True))
    for part in top_parts(target_graph):
        wanted = slots(target_graph, part)
        if wanted != tuple(range(wanted[0], wanted[-1]+1)):
            continue
        a, b = wanted[0], wanted[-1]+1
        for unit in units:
            if unit["key"] != key(target_graph, part) or unit["character"] == target_graph.character:
                continue
            source = source_repo.get(unit["character"])
            source_part = next((n for n in top_parts(source) if n.path == unit["path"]), None)
            if source_part is None or key(source, source_part) != unit["key"]:
                continue
            source_ids = [source.strokes[i].stroke_id for i in slots(source, source_part)]
            if [s for d in unit["strokes"] for s in d["slots"]] != source_ids:
                continue
            try:
                corrected_part = next(n for n in corrected.components if n.path == part.path)
                correspondence(source, source_part, corrected, corrected_part)
                curves = [np.array([(p["x"], p["y"]) for p in s["points"]]) for s in unit["strokes"]]
                placed = fit_component(curves, original[a:b])
            except (ValueError, StopIteration):
                continue
            if any(np.any(c < 0) or np.any(c > 1) for c in placed):
                continue
            mapping = dict(zip(source_ids, target_ids[a:b], strict=True))
            replaced = [[originals_by_id[mapping[s]] for s in segment["slots"]] for segment in unit["strokes"]]
            if new_relationships(placed, original[:a]+original[b:], replaced):
                continue
            candidates.append(("cross_character", [*base_segments[:a],
                                *mapped_segments(unit, mapping, placed), *base_segments[b:]]))
    return candidates


def generate(archive, repo, characters, output, references, *, same_character=False):
    from .v63_package import validate_grouped_glyph
    data = read(archive / "archive.json")
    if data["schema_version"] != ARCHIVE or data["structure_sha256"] != repo.content_sha256():
        raise ValueError("连笔档案与当前结构库不匹配")
    if not data["split_donors"] and not data["units"]:
        raise ValueError("没有可用的分笔供体或连写组")
    requested = list(dict.fromkeys(c for c in characters if not c.isspace()))
    if not requested:
        raise ValueError("请选择要生成的字符")
    split = (archive / data["split_profile"]).resolve()
    if not split.is_relative_to(archive.resolve()) or sha256_file(split) != data["split_sha256"]:
        raise ValueError("分笔对照档案完整性检查失败")
    corrected = CorrectedStructureRepository(repo, *references)
    _, compute = prepare_generation(data["writer"], repo, {"path": str(split), "sha256": data["split_sha256"]},
                                    semantic=True, reference_paths=references, candidate_limit=1)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": RUN, "writer": data["writer"], "files": {}, "failed": {},
                "requested": requested, "created_at": datetime.now(UTC).isoformat()}
    methods = Counter()
    for character in requested:
        row = compute(character, output / "v62-baseline")
        if row["status"] == "failed":
            manifest["failed"][character] = row["error"]
            continue
        baseline_path = output / "v62-baseline" / data["writer"] / f"{ord(character):04X}.json.gz"
        payload = json.loads(gzip.decompress(baseline_path.read_bytes()))
        graph = repo.get(character)
        source_rows = payload["stroke_sources"]
        base = []
        for stroke, origin in zip(payload["glyph"]["strokes"], source_rows, strict=True):
            segment = {"standard_slots": [stroke["standard_stroke_id"]], "points": stroke["points"],
                       "kind": "reference" if origin["kind"] == "explicit_gap" else "author_split"}
            if segment["kind"] == "author_split":
                segment["source_sha256"] = origin["source_sha256"]
                segment["source_character"] = origin["character"]
            base.append(segment)
        choices = candidates_for(graph, corrected.get(character), base, data["units"], repo,
                                 same_character=same_character)
        method, segments = choices[0] if choices else ("v62_fallback", base)
        glyph = {"schema_version": GLYPH, "writer_id": data["writer"], "character": character,
                 "generator": "v6.3 exp", "method": method, "standard_slots": [s.stroke_id for s in graph.strokes],
                 "segments": physical_points(segments)}
        validate_grouped_glyph(glyph, data["writer"], character)
        path = output / f"U+{ord(character):04X}.json"
        write(path, glyph)
        manifest["files"][character] = {"name": path.name, "sha256": sha256_file(path)}
        methods[method] += 1
    write(output / "v63-run.json", manifest)
    return {"completed": len(manifest["files"]), "methods": dict(methods), "failed": manifest["failed"]}
