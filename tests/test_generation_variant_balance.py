"""Bounded candidate diversity must retain checked source trajectories."""
import copy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from inkstruct.generation_v61_helpers import plan_sources
from inkstruct.generation_variants import ATTEMPT_LIMIT, alternative_candidates, geometry_key
from inkstruct.schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke
from inkstruct.trajectory_experiment import SharedTransform, assemble, crossing_pairs
from inkstruct.v61_exp import Context, Placement


class DonorEngine:
    """A deterministic fixture guard that observes the actual assembled context."""

    def __init__(self):
        self.profile = SimpleNamespace(source_trajectories={})
        self.reuse_rules = SimpleNamespace(check=lambda *args, **kwargs: {"accepted": True})
        self.calls = []
        self.rule_log = []

    def proposal(self, index, sample, points, *, character, score=0):
        source = SimpleNamespace(standard_stroke_id="recorded-stroke", points=list(points),
                                 pressure=[.35, .8], t_ms=[10, 47], confidence=.9)
        self.profile.source_trajectories[sample] = SimpleNamespace(
            character=character, sample_id=sample, source_sha256=sample + "-hash", strokes=[source])
        component = ("left", "right", "bottom-left", "bottom-right")[index]
        return Placement(component, ("s" + str(index + 1),), (index,),
                         {"character": character, "sample_id": sample,
                          "component_id": "source-part", "stroke_ids": ["recorded-stroke"],
                          "source_sha256": sample + "-hash"},
                         SharedTransform(1, 1, 0, 0), score)

    def source(self, proposal):
        sample = self.profile.source_trajectories[proposal.candidate["sample_id"]]
        by_id = {stroke.standard_stroke_id: stroke for stroke in sample.strokes}
        return [by_id[sid] for sid in proposal.candidate["stroke_ids"]]

    def placed(self, proposal):
        return [proposal.transform.apply(stroke.points) for stroke in self.source(proposal)]

    def rule_graph(self, character, *, side):
        return SimpleNamespace(character=character)

    def emit(self, ctx, plan):
        replacements = {}
        for proposal in plan.values():
            for index, stroke, points in zip(proposal.indices, self.source(proposal),
                                              self.placed(proposal), strict=True):
                replacements[index] = {"points": points, "pressure": stroke.pressure, "time": stroke.t_ms}
        return assemble(ctx.reference, replacements, "fixture")

    def attempt(self, ctx, plan, proposal, *, source_aware):
        assert source_aware
        assembled_plan = {**plan, proposal.component_id: proposal}
        glyph = self.emit(ctx, assembled_plan)
        curves = [[(point.x, point.y) for point in stroke.points] for stroke in glyph.strokes]
        crossed = bool(crossing_pairs(curves))
        evidence = {"candidate": proposal.candidate, "accepted": not crossed,
                    "fallback_reason": "fixture final-context crossing" if crossed else None}
        self.calls.append({"target": proposal.indices, "sample": proposal.candidate["sample_id"],
                           "curves": curves, "accepted": not crossed})
        return assembled_plan, evidence


def fixture(part_count=2):
    engine = DonorEngine()
    parts = [engine.proposal(index, name + "-0", points, character=character)
             for index, (name, points, character) in enumerate((
                 ("left", [(.1, .1), (.2, .2)], "甲"),
                 ("right", [(.7, .1), (.8, .2)], "乙"),
                 ("bottom-left", [(.1, .6), (.2, .7)], "丙"),
                 ("bottom-right", [(.7, .6), (.8, .7)], "丁"))[:part_count])]
    strokes = [GeneratedStroke("s" + str(i + 1), i + 1, .9,
                               [GeneratedPoint(x, y, 100 * i + t, pressure,
                                               "down" if j == 0 else ("end" if i == len(parts) - 1 else "up"))
                                for j, ((x, y), t, pressure) in enumerate(zip(
                                    engine.source(part)[0].points, (0, 37), (.35, .8), strict=True))])
               for i, part in enumerate(parts)]
    glyph = GeneratedGlyph("personal_trajectory_v1", "明", "U+660E", "zh-Hans", "fixture",
                           "fixture", "fixture", "fixture-generator", .9, strokes)
    graph = SimpleNamespace(character="明", strokes=[SimpleNamespace(stroke_id="s" + str(i + 1), order=i + 1)
                                                    for i in range(len(parts))])
    plan = {part.component_id: part for part in parts}
    ctx = Context("明", graph, glyph, glyph, {}, {part.component_id: [part] for part in parts}, plan,
                  set(), set(), set(), [])
    sources = plan_sources([asdict(part) for part in plan.values()])
    return engine, ctx, glyph, plan, sources


def generate(values):
    engine, ctx, glyph, plan, sources = values
    diagnostics = []
    result = alternative_candidates(engine, ctx, glyph, plan, sources, limit=4,
                                    cancelled=lambda: False, diagnostics=diagnostics)
    return result, diagnostics


def changed_indices(primary, candidate):
    return tuple(i for i, (before, after) in enumerate(zip(
        asdict(primary)["strokes"], candidate["glyph"]["strokes"], strict=True))
        if [(p["x"], p["y"]) for p in before["points"]]
        != [(p["x"], p["y"]) for p in after["points"]])


def test_large_first_pool_does_not_take_the_other_parts_opportunity():
    values = fixture()
    engine, ctx, primary, _, sources = values
    ctx.pools["left"] += [engine.proposal(0, f"left-{i}", [(.1, .1 + i / 100), (.2, .2 + i / 100)],
                                         character=chr(0x4F00 + i), score=i) for i in range(1, 25)]
    ctx.pools["right"].append(engine.proposal(1, "right-1", [(.7, .14), (.8, .24)], character="丁"))
    before = asdict(primary), copy.deepcopy(sources)
    candidates, diagnostics = generate(values)
    assert {changed_indices(primary, value) for value in candidates} == {(0,), (1,), (0, 1)}
    assert len(candidates) == 3
    assert any(row.get("check_count", 0) > 1 for row in diagnostics)
    assert (asdict(primary), sources) == before
    assert all(value["checks"] == {"protocol": [], "source_integrity": []} for value in candidates)


def test_first_success_waits_while_another_part_needs_a_second_source():
    values = fixture()
    engine, ctx, primary, *_ = values
    ctx.pools["left"] += [engine.proposal(0, f"left-{i}", [(.1 + i / 100, .1), (.2 + i / 100, .2)],
                                         character="丙", score=i) for i in range(1, 10)]
    ctx.pools["right"] += [
        engine.proposal(1, "right-rejected", [(.15, .05), (.15, .25)], character="丁", score=1),
        engine.proposal(1, "right-admitted", [(.73, .1), (.83, .2)], character="戊", score=2)]
    candidates, _ = generate(values)
    assert {changed_indices(primary, value) for value in candidates} == {(0,), (1,), (0, 1)}
    rejected = next(call for call in engine.calls if call["sample"] == "right-rejected")
    assert not rejected["accepted"]
    right_success = next(i for i, call in enumerate(engine.calls) if call["sample"] == "right-admitted")
    assert [call["sample"] for call in engine.calls[:right_success] if call["target"] == (0,)] == ["left-1"]
    assert all(value["provenance"][1]["sample_id"] == "right-admitted"
               for value in candidates if 1 in changed_indices(primary, value))


def test_joint_slot_can_cover_the_two_parts_not_used_by_single_candidates():
    values = fixture(part_count=4)
    engine, ctx, primary, plan, _ = values
    for index, part in enumerate(plan.values()):
        points = [(x + .015, y + .01) for x, y in engine.source(part)[0].points]
        ctx.pools[part.component_id].append(engine.proposal(
            index, part.component_id + "-1", points, character=part.candidate["character"], score=1))
    candidates, _ = generate(values)
    changes = [set(changed_indices(primary, value)) for value in candidates]
    assert len(candidates) == 3 and sorted(map(len, changes)) == [1, 1, 2]
    singles = set().union(*(change for change in changes if len(change) == 1))
    joint = next(change for change in changes if len(change) == 2)
    assert not singles.intersection(joint)
    assert singles.union(joint) == {0, 1, 2, 3}


def test_other_recordings_of_same_donor_are_eligible_but_duplicate_ink_is_not():
    values = fixture()
    engine, ctx, primary, *_ = values
    for sample, dy in (("left-1", .02), ("left-2", .02), ("left-3", 0)):
        ctx.pools["left"].append(engine.proposal(0, sample, [(.1, .1 + dy), (.2, .2 + dy)], character="甲"))
    candidates, diagnostics = generate(values)
    assert len(candidates) == 1
    assert candidates[0]["provenance"][0]["character"] == "甲"
    assert candidates[0]["provenance"][0]["sample_id"] == "left-1"
    assert geometry_key(candidates[0]["glyph"]) != geometry_key(asdict(primary))
    assert any("duplicate" in str(value).lower() for value in diagnostics)


def test_joint_context_failure_cannot_pass_using_individual_admission():
    values = fixture()
    engine, ctx, primary, *_ = values
    ctx.pools["left"].append(engine.proposal(0, "left-1", [(.2, .3), (.6, .3)], character="丙"))
    ctx.pools["right"].append(engine.proposal(1, "right-1", [(.5, .2), (.5, .4)], character="丁"))
    candidates, diagnostics = generate(values)
    assert {changed_indices(primary, value) for value in candidates} == {(0,), (1,)}
    assert any(not call["accepted"] for call in engine.calls)
    assert any("crossing" in str(value) for value in diagnostics)
    for value in candidates:
        assert not crossing_pairs([[(p["x"], p["y"]) for p in stroke["points"]]
                                   for stroke in value["glyph"]["strokes"]])


def test_pool_insertion_order_and_repetition_do_not_change_candidates():
    values = fixture()
    engine, ctx, *_ = values
    for index, key, char in ((0, "left", "丙"), (1, "right", "丁")):
        for i in range(1, 4):
            start = .1 if index == 0 else .7
            ctx.pools[key].append(engine.proposal(index, key + str(i),
                                                  [(start, .1 + i / 100), (start + .1, .2 + i / 100)],
                                                  character=char, score=i))
    first, _ = generate(values)
    for key in ctx.pools:
        ctx.pools[key].reverse()
    ctx.baseline_plan = dict(reversed(list(ctx.baseline_plan.items())))
    reordered = (engine, ctx, values[2], ctx.baseline_plan, values[4])
    second, _ = generate(reordered)
    assert first == second
    assert first == generate(reordered)[0]


def test_rejected_proposals_share_the_fixed_attempt_budget():
    values = fixture()
    engine, ctx, *_ = values
    for index, key, char in ((0, "left", "丙"), (1, "right", "丁")):
        ctx.pools[key] += [engine.proposal(index, f"{key}-{i}", [(.2, .2), (.8, .8)],
                                          character=char, score=i) for i in range(1, 40)]
    original = engine.attempt
    def reject(ctx, plan, proposal, *, source_aware):
        result, evidence = original(ctx, plan, proposal, source_aware=source_aware)
        evidence.update(accepted=False, fallback_reason="fixture admission rejection")
        return result, evidence
    engine.attempt = reject
    candidates, diagnostics = generate(values)
    assert not candidates
    assert 2 <= len(engine.calls) <= ATTEMPT_LIMIT == 16
    assert {call["target"] for call in engine.calls[:2]} == {(0,), (1,)}
    attempts = [row["attempt"] for row in diagnostics if "attempt" in row]
    assert attempts and max(attempts) <= ATTEMPT_LIMIT
    assert len(attempts) == len(set(attempts))


def test_last_round_robin_turn_is_not_restarted_at_the_first_pool():
    values = fixture()
    engine, ctx, primary, *_ = values
    for index, key, count, character in ((0, "left", 9, "丙"), (1, "right", 8, "丁")):
        start = .1 if index == 0 else .7
        ctx.pools[key] += [engine.proposal(index, f"{key}-{i}",
                                          [(start, .1 + i / 100), (start + .1, .2 + i / 100)],
                                          character=character, score=i) for i in range(1, count + 1)]
    original = engine.attempt
    def admit_last_right(ctx, plan, proposal, *, source_aware):
        result, evidence = original(ctx, plan, proposal, source_aware=source_aware)
        if proposal.candidate["sample_id"] != "right-8":
            evidence.update(accepted=False, fallback_reason="fixture admission rejection")
        return result, evidence
    engine.attempt = admit_last_right
    candidates, diagnostics = generate(values)
    assert engine.calls[-1]["sample"] == "right-8"
    assert len(candidates) == 1 and changed_indices(primary, candidates[0]) == (1,)
    assert candidates[0]["provenance"][1]["sample_id"] == "right-8"
    attempts = [row["attempt"] for row in diagnostics if "attempt" in row]
    assert len(attempts) == max(attempts) == ATTEMPT_LIMIT == 16


def test_last_budget_turn_keeps_searching_the_unresolved_part():
    values = fixture()
    engine, ctx, primary, *_ = values
    ctx.pools["left"] += [engine.proposal(0, f"left-{i}", [(.1, .1 + i / 100), (.2, .2 + i / 100)],
                                         character="丙", score=i) for i in (1, 2)]
    ctx.pools["right"] += [engine.proposal(1, f"right-{i}", [(.7, .1 + i / 100), (.8, .2 + i / 100)],
                                          character="丁", score=i) for i in range(1, 16)]
    original = engine.attempt
    def admit_left_and_last_right(ctx, plan, proposal, *, source_aware):
        result, evidence = original(ctx, plan, proposal, source_aware=source_aware)
        if proposal.candidate["sample_id"] not in {"left-1", "right-15"}:
            evidence.update(accepted=False, fallback_reason="fixture admission rejection")
        return result, evidence
    engine.attempt = admit_left_and_last_right
    candidates, diagnostics = generate(values)
    samples = [call["sample"] for call in engine.calls]
    assert samples[-1] == "right-15" and "left-2" not in samples
    assert {changed_indices(primary, value) for value in candidates} == {(0,), (1,)}
    assert any(value["provenance"][1]["sample_id"] == "right-15" for value in candidates)
    attempts = [row["attempt"] for row in diagnostics if "attempt" in row]
    assert len(attempts) == max(attempts) == ATTEMPT_LIMIT == 16


@pytest.mark.parametrize("reason", ["cancelled", "source_gap", "limit_one"])
def test_early_exit_never_attempts_or_modifies_the_primary(reason):
    engine, ctx, primary, plan, sources = fixture()
    before = asdict(primary)
    if reason == "source_gap":
        sources.pop(1)
    result = alternative_candidates(engine, ctx, primary, plan, sources,
                                    limit=1 if reason == "limit_one" else 4,
                                    cancelled=lambda: reason == "cancelled", diagnostics=[])
    assert result == [] and not engine.calls
    assert asdict(primary) == before
