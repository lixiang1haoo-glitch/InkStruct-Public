"""User-selected candidate counts retain admission and font resource boundaries."""
import copy
import json
import zipfile
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from test_generation_variant_balance import changed_indices, fixture
from test_generation_variants import CHARACTER, PROFILE, WRITER, payload_for, write_run

from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font
from inkstruct.generation_parallel import run_generation, verify_row
from inkstruct.generation_variants import (
    DEFAULT_CANDIDATES,
    MAX_CANDIDATES,
    POOL_VERSION,
    alternative_candidates,
    candidate_attempt_limit,
)
from inkstruct.generation_workflow import GenerationWorkflow, generate_v61, write
from inkstruct.samples import sha256_file


@pytest.mark.parametrize("limit,budget", [(1, 0), (2, 16), (3, 16), (4, 16), (8, 32), (23, 92), (64, 256)])
def test_requested_count_has_a_finite_attempt_budget(limit, budget):
    assert DEFAULT_CANDIDATES == 4 and MAX_CANDIDATES == 64
    assert candidate_attempt_limit(limit) == budget


@pytest.mark.parametrize("invalid", [0, -1, 65, True, 8.0, "8", None])
def test_invalid_count_is_rejected_before_resources_or_output_are_touched(tmp_path, invalid):
    with pytest.raises(ValueError):
        candidate_attempt_limit(invalid)
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        run_generation(output, WRITER, [CHARACTER], None, {}, None, lambda: False,
                       semantic=True, candidate_limit=invalid)
    assert not output.exists()


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 8, 23, 64])
def test_candidate_count_respects_the_requested_limit_without_duplicates(limit):
    engine, ctx, primary, plan, sources = fixture()
    for index, key, character in ((0, "left", "丙"), (1, "right", "丁")):
        start = .1 if index == 0 else .7
        ctx.pools[key] += [engine.proposal(
            index, f"{key}-{i}", [(start, .1 + i / 1000), (start + .1, .2 + i / 1000)],
            character=character, score=i) for i in range(1, 65)]
    diagnostics = []
    candidates = alternative_candidates(engine, ctx, primary, plan, sources, limit=limit,
                                        cancelled=lambda: False, diagnostics=diagnostics)
    assert len(candidates) + 1 == limit
    geometries = [tuple(tuple((p["x"], p["y"]) for p in stroke["points"])
                        for stroke in value["glyph"]["strokes"]) for value in candidates]
    assert len(geometries) == len(set(geometries))
    attempts = [row["attempt"] for row in diagnostics if "attempt" in row]
    assert len(attempts) <= candidate_attempt_limit(limit)
    assert all(value["checks"] == {"protocol": [], "source_integrity": []} for value in candidates)


def candidate_run(folder, limit):
    primary = payload_for("信", 0)
    extended = copy.deepcopy(primary)
    extended["candidate_pool"] = {"version": POOL_VERSION, "alternatives": [
        payload_for(chr(0x4F00 + i), (i + 1) / 1000) for i in range(limit - 1)]}
    row = write_run(folder, extended, limit=limit, count=limit)
    protocol = json.loads((folder / "protocol.json").read_text("utf-8"))
    protocol["candidate_pool"]["attempt_limit"] = candidate_attempt_limit(limit)
    write(folder / "protocol.json", protocol)
    return primary, row


@pytest.mark.parametrize("limit", [4, 8, 64])
def test_all_requested_candidates_import_and_preserve_the_original_id(tmp_path, limit):
    primary, row = candidate_run(tmp_path / "new", limit)
    verify_row(tmp_path / "new", WRITER, CHARACTER, row, PROFILE, candidate_limit=limit)
    write_run(tmp_path / "old", primary, limit=1)
    before_path, after_path = tmp_path / "old.inkfont", tmp_path / "new.inkfont"
    for output, source in ((before_path, "old"), (after_path, "new")):
        build_font(output, writer=WRITER, name="same candidate identity", run=tmp_path / source)
    before, after = FontPackage(before_path), FontPackage(after_path)
    assert after.verify()["candidates"] == limit
    assert before.records[0] in after.records
    assert len({record["geometry_hash"] for record in after.records}) == limit


def test_task_count_still_limits_rows_when_the_global_limit_is_larger(tmp_path):
    _, row = candidate_run(tmp_path / "run", 9)
    protocol = json.loads((tmp_path / "run/protocol.json").read_text("utf-8"))
    protocol["candidate_pool"]["limit"] = 8
    protocol["candidate_pool"]["attempt_limit"] = candidate_attempt_limit(8)
    write(tmp_path / "run/protocol.json", protocol)
    with pytest.raises(ValueError):
        verify_row(tmp_path / "run", WRITER, CHARACTER, row, PROFILE, candidate_limit=8)
    with pytest.raises(ValueError):
        build_font(tmp_path / "bad.inkfont", writer=WRITER, name="bad", run=tmp_path / "run")
    assert not (tmp_path / "bad.inkfont").exists()


@pytest.mark.parametrize("boundary", ["member", "total", "points"])
def test_large_candidate_pool_still_enforces_font_resource_limits(tmp_path, monkeypatch, boundary):
    from inkstruct.fonts import core

    candidate_run(tmp_path / "run", 64)
    package = tmp_path / "many.inkfont"
    build_font(package, writer=WRITER, name="many", run=tmp_path / "run")
    assert FontPackage(package).verify()["candidates"] == 64
    with zipfile.ZipFile(package) as archive:
        sizes = [info.file_size for info in archive.infolist()]
    if boundary == "member":
        monkeypatch.setattr(core, "MAX_MEMBER", max(sizes) - 1)
    elif boundary == "total":
        monkeypatch.setattr(core, "MAX_TOTAL", sum(sizes) - 1)
    else:
        monkeypatch.setattr(core, "MAX_POINTS", 3)
    with pytest.raises(ValueError):
        FontPackage(package).verify()


def test_larger_count_still_rejects_joint_context_conflicts():
    engine, ctx, primary, plan, sources = fixture()
    ctx.pools["left"].append(engine.proposal(0, "left-1", [(.2, .3), (.6, .3)], character="丙"))
    ctx.pools["right"].append(engine.proposal(1, "right-1", [(.5, .2), (.5, .4)], character="丁"))
    diagnostics = []
    candidates = alternative_candidates(engine, ctx, primary, plan, sources, limit=8,
                                        cancelled=lambda: False, diagnostics=diagnostics)
    assert {changed_indices(primary, value) for value in candidates} == {(0,), (1,)}
    assert any(len(row.get("target_components", [])) == 2 and not row["accepted"]
               for row in diagnostics)


def test_eight_candidate_budget_bounds_rejected_proposals_to_thirty_two():
    engine, ctx, primary, plan, sources = fixture()
    before = asdict(primary), copy.deepcopy(sources)
    for index, key, char in ((0, "left", "丙"), (1, "right", "丁")):
        start = .1 if index == 0 else .7
        ctx.pools[key] += [engine.proposal(index, f"{key}-{i}",
                                          [(start, .1 + i / 1000), (start + .1, .2 + i / 1000)],
                                          character=char, score=i) for i in range(1, 41)]
    original = engine.attempt
    def reject(*args, **kwargs):
        result, evidence = original(*args, **kwargs)
        evidence.update(accepted=False, fallback_reason="fixture rejection")
        return result, evidence
    engine.attempt = reject
    diagnostics = []
    assert alternative_candidates(engine, ctx, primary, plan, sources, limit=8,
                                  cancelled=lambda: False, diagnostics=diagnostics) == []
    assert len(engine.calls) == 32
    assert [row["attempt"] for row in diagnostics if "attempt" in row] == list(range(1, 33))
    assert diagnostics[-1]["stop_reason"] == "attempt limit"
    assert (asdict(primary), sources) == before


def test_joint_proposal_uses_the_last_eight_candidate_attempt_and_checks_both_parts():
    engine, ctx, primary, plan, sources = fixture()
    ctx.pools["left"].append(engine.proposal(0, "left-1", [(.11, .1), (.21, .2)], character="丙"))
    ctx.pools["right"] += [engine.proposal(1, f"right-{i}",
                                          [(.7, .1 + i / 1000), (.8, .2 + i / 1000)],
                                          character="丁", score=i) for i in range(1, 31)]
    original = engine.attempt
    def last_right(*args, **kwargs):
        result, evidence = original(*args, **kwargs)
        if args[2].candidate["sample_id"] not in {"left-1", "right-30"}:
            evidence.update(accepted=False, fallback_reason="fixture rejection")
        return result, evidence
    engine.attempt = last_right
    diagnostics = []
    candidates = alternative_candidates(engine, ctx, primary, plan, sources, limit=8,
                                        cancelled=lambda: False, diagnostics=diagnostics)
    attempts = [row for row in diagnostics if "attempt" in row]
    assert len(attempts) == 32 and len(engine.calls) == 33
    assert attempts[-1]["attempt"] == 32 and attempts[-1]["check_count"] == 2
    assert attempts[-1]["accepted"]
    assert {changed_indices(primary, value) for value in candidates} == {(0,), (1,), (0, 1)}
    assert diagnostics[-1]["attempt_limit"] == 32


def test_cancel_during_extra_candidates_stops_new_proposals_and_preserves_primary():
    engine, ctx, primary, plan, sources = fixture()
    for index, key, char in ((0, "left", "丙"), (1, "right", "丁")):
        start = .1 if index == 0 else .7
        ctx.pools[key] += [engine.proposal(index, f"{key}-{i}",
                                          [(start, .1 + i / 1000), (start + .1, .2 + i / 1000)],
                                          character=char, score=i) for i in range(1, 10)]
    before = asdict(primary), copy.deepcopy(sources)
    cancelled = False
    original = engine.attempt
    def cancel_after_third_check(*args, **kwargs):
        nonlocal cancelled
        result = original(*args, **kwargs)
        cancelled = cancelled or len(engine.calls) == 3
        return result
    engine.attempt = cancel_after_third_check
    diagnostics = []
    candidates = alternative_candidates(engine, ctx, primary, plan, sources, limit=8,
                                        cancelled=lambda: cancelled, diagnostics=diagnostics)
    # Cancellation stops new proposals; the current joint proposal completes
    # both final-context checks rather than publishing a half-checked variant.
    assert len(engine.calls) == 4 and diagnostics[-1]["attempts"] == 3
    assert diagnostics[-1]["stop_reason"] == "cancelled"
    assert all(value["checks"] == {"protocol": [], "source_integrity": []} for value in candidates)
    assert (asdict(primary), sources) == before


@pytest.fixture
def service(tmp_path, monkeypatch):
    from inkstruct import structures

    database, profile, index = [tmp_path / name for name in ("db", "profile", "index")]
    for path in (database, profile, index):
        path.write_text(path.name, encoding="utf-8")
    record = {"path": str(profile), "sha256": sha256_file(profile),
              "database_sha256": sha256_file(database), "index_sha256": sha256_file(index)}
    state = {"profiles": {method: record for method in ("v62", "v61", "v4")},
             "import": {"index": str(index)}}
    workflow = GenerationWorkflow(tmp_path / "work", database)
    monkeypatch.setattr(workflow, "require", lambda *args: None)
    monkeypatch.setattr(workflow, "state", lambda *args: state)
    monkeypatch.setattr(structures, "StructureRepository", lambda path: SimpleNamespace(
        path=path, characters=lambda: list("孔正")))
    return workflow


@pytest.mark.parametrize("method,requested,expected", [
    ("v62", None, 4), ("v62", 1, 1), ("v62", 8, 8), ("v62", 64, 64),
    ("v61", None, 1), ("v61", 1, 1)])
def test_workflow_propagates_user_count_and_retains_method_behavior(service, monkeypatch,
                                                                    method, requested, expected):
    import inkstruct.generation_workflow as workflow

    received = []
    def generate(*args, **kwargs):
        received.append(kwargs)
        return {"completed_count": 2, "failed_count": 0}
    monkeypatch.setattr(workflow, "generate_v61", generate)
    service.generate(WRITER, "samples", method, "孔正", candidate_limit=requested)
    assert received[0]["candidate_limit"] == expected
    assert received[0]["semantic"] == (method == "v62")


@pytest.mark.parametrize("method", ["v61", "v4"])
def test_unsupported_method_rejects_multiple_candidates_before_loading_resources(service, monkeypatch,
                                                                                 method):
    def no_resources(*args):
        raise AssertionError("resource access before count validation")
    monkeypatch.setattr(service, "require", no_resources)
    with pytest.raises(ValueError, match="v6.2 exp"):
        service.generate(WRITER, "samples", method, "孔正", candidate_limit=8)


def test_v4_retains_its_single_candidate_path(service, monkeypatch, tmp_path):
    import inkstruct.generate as generation

    calls = []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        return {"completed_count": 2, "failed_count": 0}, tmp_path / "v4-output"
    monkeypatch.setattr(generation, "generate_run", generate)
    result = service.generate(WRITER, "samples", "v4", "孔正")
    assert result["completed_count"] == 2
    assert len(calls) == 1 and "candidate_limit" not in calls[0]


def test_low_level_generation_keeps_legacy_single_candidate_default(monkeypatch):
    import inkstruct.generation_parallel as parallel

    received = []
    monkeypatch.setattr(parallel, "run_generation", lambda *args, **kwargs: received.append(kwargs))
    generate_v61("unused", WRITER, [CHARACTER], None, {}, None, lambda: False)
    assert received[0]["candidate_limit"] == 1
