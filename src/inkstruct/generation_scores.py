"""Score validated generation candidates using the font packer's default priorities."""

from itertools import groupby
from statistics import fmean

from .fonts.importer import font_candidate_priority, generated_records, make_generated
from .generation_variants import geometry_key


def diversity_points(count):
    return 100 * (1 - 2 ** (-max(count - 1, 0) / 3))


def stroke_source_points(kind):
    return 80 if kind in {"author_complete_component", "author_group"} else 0 if kind in {"explicit_gap", "reference"} else 60


def source_points(glyph, payload):
    if glyph.get("method") == "same_character":
        return 100.0
    if "segments" in glyph:
        segments = glyph["segments"]
        return fmean((stroke_source_points(segment.get("source_kind", segment["kind"])) for segment in segments),
                     weights=(len(segment["standard_slots"]) for segment in segments))
    return fmean(stroke_source_points(row["kind"]) for row in payload["stroke_sources"])


def evaluate(run, writer, targets, *, source, diversity, completed):
    targets = set(targets)
    total = len(targets)
    source_total = diversity_total = replayed = rotatable = covered = 0
    records = generated_records(run, writer) if completed else ()
    for character, candidates in groupby(records, key=lambda record: record[0]["character"]):
        if character not in targets:
            continue
        choices = []
        for glyph, row, payload, protocol in candidates:
            trajectory, _, summary = make_generated(glyph, row, payload, protocol)
            choices.append((font_candidate_priority(summary), trajectory, glyph, payload))
        priority = min(c[0] for c in choices)
        active = [(trajectory, glyph, payload) for rank, trajectory, glyph, payload in choices if rank == priority]
        covered += 1
        if source:
            source_total += fmean(source_points(glyph, payload) for _, glyph, payload in active)
            replayed += any(glyph.get("method") == "same_character" for _, glyph, _ in active)
        if diversity:
            n = len({geometry_key(trajectory) for trajectory, _, _ in active})
            diversity_total += diversity_points(n)
            rotatable += n >= 2
    result = {"target_count": total, "covered_count": covered}
    if source:
        result.update(source_score=source_total / total, replayed_count=replayed)
    if diversity:
        result.update(diversity_score=diversity_total / total, rotatable_count=rotatable)
    return result
