"""Admit connected archives and generate whole replays or connected transfers."""

from dataclasses import asdict

import numpy as np

from .placement import connected_relationship_failure
from .contacts import BRUSH_WIDTH, segment_clearance
from .trace import Donor, emit, observer
from ..generation_workflow import write
from ..samples import iter_index, sha256_file
from .components import correspondence
from .alignment import align_groups


ARCHIVE = "inkstruct_v63_group_archive_v1"
GLYPH = "inkstruct_v63_grouped_glyph_v1"
CONNECTED_METHOD = "v6.3.1"


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


def build_connected_profile(writer, index, repo, profile, profile_path):
    units, review = collect_units(iter_index(index), repo, profile.source_trajectories)
    path = profile_path.with_name("connected.json")
    write(path, {"schema_version": ARCHIVE, "writer": writer, "units": units, "review": review})
    return {"path": str(path), "sha256": sha256_file(path), "samples": len({u["sample"] for u in units}),
            "whole": sum(u["path"] == "whole" for u in units),
            "parts": sum(u["path"] != "whole" for u in units)}


def collect_units(samples, repo, split_donors):
    units, reviewed = [], []
    for sample in samples:
        if sample.sample_id in split_donors:
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
    return units, reviewed


def fit_component(source, target, *, measurements=None):
    src = np.concatenate(source)
    dst = np.concatenate(target)
    a, b = src.min(axis=0), src.max(axis=0)
    c, d = dst.min(axis=0), dst.max(axis=0)
    if min(min(b-a), min(d-c)) <= 1e-8:
        raise ValueError("部件范围不足")
    ratios = (d-c)/(b-a)
    if max(ratios)/min(ratios) > 1.65:
        raise ValueError("目标部件比例差异过大")
    if measurements is not None:
        measurements.update(scale=float(min(ratios)), source_center=((a+b)/2).tolist(),
                            target_center=((c+d)/2).tolist())
    return [(trace-(a+b)/2)*min(ratios)+(c+d)/2 for trace in source]


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


def same_character_candidates(writer, graph, split_samples, connected_units, *, limit, cancelled):
    from .alternatives import geometry_key
    from ..source_trajectory import MIN_MAPPING_CONFIDENCE
    from .stroke_sources import valid_source
    from ..v63_package import validate_grouped_glyph

    standard = [stroke.stroke_id for stroke in graph.strokes]
    identity = {slot: slot for slot in standard}

    def originals():
        for sample in split_samples:
            if cancelled():
                return
            if (sample.character != graph.character
                    or sample.stroke_order_status not in {"declared", "corrected"}
                    or [stroke.standard_stroke_id for stroke in sample.strokes] != standard
                    or sorted(stroke.user_order for stroke in sample.strokes) != list(range(1, len(standard) + 1))
                    or not all(stroke.confidence >= MIN_MAPPING_CONFIDENCE and valid_source(stroke)
                               for stroke in sample.strokes)):
                continue
            yield [{"standard_slots": [stroke.standard_stroke_id], "kind": "author_split",
                    "source_character": sample.character, "source_sha256": sample.source_sha256,
                    "source_raw_order": stroke.user_order,
                    "points": [{"x": xy[0], "y": xy[1], "pressure": pressure, "t_ms": time}
                               for xy, pressure, time in zip(stroke.points, stroke.pressure, stroke.t_ms, strict=True)]}
                   for stroke in sample.strokes]
        for unit in connected_units:
            if cancelled():
                return
            if (unit["path"] == "whole" and unit["character"] == graph.character
                    and [slot for stroke in unit["strokes"] for slot in stroke["slots"]] == standard):
                yield mapped_segments(unit, identity)

    result, seen = [], set()
    sink = observer()
    if sink is not None:
        emit(sink, "same character", "retrieval", "found" if split_samples or connected_units else "no candidates",
             split=len(split_samples), connected=len(connected_units), budget=limit, target=standard)
    for segments in originals():
        signature = geometry_key({"strokes": segments})
        if signature in seen:
            continue
        glyph = {"schema_version": GLYPH, "writer_id": writer, "character": graph.character,
                 "generator": CONNECTED_METHOD, "method": "same_character",
                 "standard_slots": standard, "segments": physical_points(segments)}
        try:
            validate_grouped_glyph(glyph, writer, graph.character)
        except ValueError:
            continue
        seen.add(signature)
        result.append(glyph)
        if sink is not None:
            emit(sink, "same character", "decision", "adopted", target=standard,
                 source_sha256=segments[0]["source_sha256"], segment_count=len(segments))
        if len(result) == limit:
            break
    return result


def matching_units(units, target_graph, part, cancelled):
    for unit in units:
        if cancelled():
            break
        if unit["key"] == key(target_graph, part) and unit["character"] != target_graph.character:
            yield unit


def admit_connected(unit, part, corrected, source_repo):
    source = source_repo.get(unit["character"])
    source_part = next((n for n in top_parts(source) if n.path == unit["path"]), None)
    if source_part is None or key(source, source_part) != unit["key"]:
        return None, "source component identity"
    source_ids = [source.strokes[i].stroke_id for i in slots(source, source_part)]
    if [s for d in unit["strokes"] for s in d["slots"]] != source_ids:
        return None, "incomplete ordered physical slots"
    try:
        corrected_part = next(n for n in corrected.components if n.path == part.path)
        correspondence(source, source_part, corrected, corrected_part)
    except (ValueError, StopIteration) as error:
        return None, str(error) or "target component not present in corrected reference"
    return source_ids, None


def candidates_for(target_graph, corrected, base_segments, units, source_repo, *, same_character,
                   cancelled=lambda: False, writer=""):
    target_ids = [s.stroke_id for s in target_graph.strokes]
    candidates = []
    sink = observer()
    if same_character:
        for u in units:
            if u["path"] == "whole" and u["character"] == target_graph.character:
                identity = {i: i for i in target_ids}
                candidates.append(("same_character", mapped_segments(u, identity)))
    original = [np.array([(p["x"], p["y"]) for p in seg["points"]]) for seg in base_segments]
    originals_by_id = dict(zip(target_ids, original, strict=True))
    for part in top_parts(target_graph):
        if cancelled():
            break
        wanted = slots(target_graph, part)
        if wanted != tuple(range(wanted[0], wanted[-1]+1)):
            continue
        a, b = wanted[0], wanted[-1]+1
        retrieved = 0
        for unit in matching_units(units, target_graph, part, cancelled):
            retrieved += 1
            donor = None
            if sink is not None:
                donor = Donor(writer, unit["character"], unit["sample"], unit["source_sha256"],
                              tuple(s["raw_order"] for s in unit["strokes"]), tuple(target_ids[a:b]))
                emit(sink, "connected", "retrieval", "found", donor=donor, index=part.path)
            source_ids, reason = admit_connected(unit, part, corrected, source_repo)
            if sink is not None:
                emit(sink, "connected", "admission", "accepted" if source_ids is not None else "rejected",
                     donor=donor, reason=reason)
            if source_ids is None:
                continue
            try:
                curves = [np.array([(p["x"], p["y"]) for p in s["points"]]) for s in unit["strokes"]]
                measurements = {} if sink is not None else None
                placed = fit_component(curves, original[a:b], measurements=measurements)
            except (ValueError, StopIteration) as error:
                if sink is not None:
                    emit(sink, "connected", "placement", "rejected", donor=donor, reason=str(error))
                continue
            if any(np.any(c < 0) or np.any(c > 1) for c in placed):
                if sink is not None:
                    emit(sink, "connected", "placement", "rejected", donor=donor, reason="bounds",
                         transform=measurements)
                continue
            mapping = dict(zip(source_ids, target_ids[a:b], strict=True))
            replaced = [[originals_by_id[mapping[s]] for s in segment["slots"]] for segment in unit["strokes"]]
            failure = connected_relationship_failure(placed, original[:a]+original[b:], replaced)
            if sink is not None:
                relation = None
                if failure:
                    why, segment, external = failure
                    neighbor = external if external < a else external + (b - a)
                    relation = {"reason": why, "physical_order": unit["strokes"][segment]["raw_order"],
                                "covered_slots": [mapping[s] for s in unit["strokes"][segment]["slots"]],
                                "neighbor_slot": target_ids[neighbor], "brush_width_em": BRUSH_WIDTH,
                                "clearance_em": segment_clearance(placed[segment], original[neighbor])}
                emit(sink, "connected", "placement", "rejected" if failure else "eligible",
                     donor=donor, relation=relation, transform=measurements)
            if failure:
                continue
            candidates.append(("cross_character", [*base_segments[:a],
                                *mapped_segments(unit, mapping, placed), *base_segments[b:]]))
        if sink is not None:
            emit(sink, "connected", "retrieval summary", "found" if retrieved else "no candidates",
                 target=target_ids[a:b], index=part.path, count=retrieved)
    return candidates


def connected_candidates(writer, graph, corrected, base_glyph, source_rows, units, repo, *,
                         same_character, limit, cancelled=lambda: False):
    from .alternatives import geometry_key
    from ..v63_package import validate_grouped_glyph

    if not units:
        return []
    base = []
    for stroke, origin in zip(base_glyph["strokes"], source_rows, strict=True):
        segment = {"standard_slots": [stroke["standard_stroke_id"]], "points": stroke["points"],
                   "kind": "reference" if origin["kind"] == "explicit_gap" else "author_split"}
        if segment["kind"] == "author_split":
            segment["source_sha256"] = origin["source_sha256"]
            segment["source_character"] = origin["character"]
            segment["source_kind"] = origin["kind"]
        base.append(segment)
    result, seen = [], set()
    for method, segments in candidates_for(graph, corrected, base, units, repo,
                                            same_character=same_character, cancelled=cancelled, writer=writer):
        signature = geometry_key({"strokes": segments})
        if signature in seen:
            continue
        seen.add(signature)
        glyph = {"schema_version": GLYPH, "writer_id": writer, "character": graph.character,
                 "generator": CONNECTED_METHOD, "method": method,
                 "standard_slots": [s.stroke_id for s in graph.strokes], "segments": physical_points(segments)}
        validate_grouped_glyph(glyph, writer, graph.character)
        result.append(glyph)
        if len(result) >= limit:
            break
    return result
