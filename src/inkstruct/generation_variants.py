"""Additional source-preserving candidates for one already completed character."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, replace
from itertools import combinations

from .generation_v61_helpers import (
    LABELS,
    check_sources,
    compact_sources,
    plan_sources,
    source_audit,
)
from .trajectory_experiment import assemble, invariants
from .v61_author_strokes import valid_source

POOL_VERSION = "inkstruct-real-donor-candidates-v1"
DEFAULT_CANDIDATES = 4
MAX_CANDIDATES = 64
ATTEMPT_LIMIT = 16
SELECTION_POLICY = "balanced-complete-parts-pairs-v1"


def geometry_key(glyph):
    return tuple(tuple((p["x"], p["y"]) for p in s["points"]) for s in glyph["strokes"])


def candidate_attempt_limit(count):
    if type(count) is not int or not 1 <= count <= MAX_CANDIDATES:
        raise ValueError(f"每字成品上限须为 1–{MAX_CANDIDATES} 的整数")
    return 0 if count == 1 else max(ATTEMPT_LIMIT, count * 4)


def source_key(placement):
    candidate = placement.candidate
    return (candidate["sample_id"], candidate["source_sha256"],
            candidate["component_id"], tuple(candidate["stroke_ids"]))


def alternative_candidates(engine, ctx, primary, plan, sources, *, limit, cancelled, diagnostics):
    """Balance complete-part alternatives, then try bounded pairs of real samples.

    One attempt is one complete replacement proposal, including a pair. A pair
    rechecks each part against the final placement of the other part. Once two
    parts have alternatives, the initial search reserves one available
    attempt for a joint proposal. Otherwise the same fair search uses the last
    attempt too. Failed joints fall back to validated single changes. The budget
    scales with the requested count and remains sixteen for the default four.
    """
    attempt_limit = candidate_attempt_limit(limit)
    if limit == 1 or len(sources) != len(primary.strokes):
        diagnostics.append({"stage": "availability", "reason": "disabled or primary source gaps"})
        return []
    comparison = replace(ctx, reference=primary)
    seen = {geometry_key(asdict(primary))}
    attempts = 0

    def assess(proposals):
        nonlocal attempts
        if cancelled() or attempts >= attempt_limit:
            return None
        attempts += 1
        evidence = {"attempt": attempts, "target_components": [p.component_id for p in proposals],
                    "candidates": [p.candidate for p in proposals], "checks": [],
                    "check_count": 0, "accepted": False}
        diagnostics.append(evidence)
        replacements, provenance = {}, dict(sources)
        try:
            for proposal in proposals:
                if set(proposal.indices).intersection(replacements):
                    raise ValueError("overlapping component ownership")
                recorded = engine.source(proposal)
                if not all(valid_source(stroke) for stroke in recorded):
                    raise ValueError("invalid recorded stroke dynamics")
                placed = engine.placed(proposal)
                for i, points, stroke in zip(proposal.indices, placed, recorded, strict=True):
                    replacements[i] = {"points": points, "pressure": stroke.pressure, "time": stroke.t_ms}
                provenance.update(plan_sources([asdict(proposal)]))
            expected = {p.component_id for p in proposals}
            for proposal in proposals:
                other_changes = {p.component_id: p for p in proposals if p is not proposal}
                checked, check = engine.attempt(comparison, other_changes, proposal, source_aware=True)
                evidence["checks"].append(check)
                evidence["check_count"] += 1
                if not check["accepted"]:
                    evidence["fallback_reason"] = check.get("fallback_reason", "final-context rejection")
                    return None
                if set(checked) != expected:
                    raise ValueError("final-context guard removed a combined component")
            glyph = assemble(primary, replacements, "real_donor_variant")
            glyph.generator = primary.generator
            glyph.canvas_fit = primary.canvas_fit
            for i in replacements:
                glyph.strokes[i].style_source = primary.strokes[i].style_source
            source_audit(engine, ctx.graph, provenance)
            checks = {"protocol": invariants(glyph, ctx.graph),
                      "source_integrity": check_sources(engine.profile, glyph, provenance)}
        except ValueError as error:
            evidence["fallback_reason"] = str(error)
            return None
        if any(checks.values()):
            evidence["final_candidate_checks"] = checks
            return None
        value = asdict(glyph)
        signature = geometry_key(value)
        if signature in seen:
            evidence["fallback_reason"] = "duplicate candidate geometry"
            return None
        seen.add(signature)
        evidence["accepted"] = True
        rows, _, gaps = compact_sources(ctx.graph, provenance, [])
        assert not gaps
        return {"glyph": value, "provenance": provenance, "stroke_sources": rows,
                "missing": [], "checks": checks, "author_only_ready": True,
                "variant_admission": evidence}

    pools = []
    for part in sorted(plan.values(), key=lambda p: (p.indices, p.component_id)):
        original = plan_sources([asdict(part)])
        if any(sources.get(i) != p for i, p in original.items()):
            diagnostics.append({"stage": "availability", "target_component": part.component_id,
                                "reason": "part no longer intact in primary"})
            continue
        identities = {source_key(part)}
        pool = deque()
        for proposal in sorted(ctx.pools.get(part.component_id, ()),
                               key=lambda p: (p.base_score, source_key(p),
                                              tuple(asdict(p.transform).values()))):
            key = source_key(proposal)
            if (key in identities or proposal.ids != part.ids or proposal.indices != part.indices
                    or proposal.candidate["character"] == ctx.character):
                continue
            identities.add(key)
            pool.append(proposal)
        if pool:
            pools.append(pool)
        else:
            diagnostics.append({"stage": "availability", "target_component": part.component_id,
                                "reason": "no distinct complete source instance"})

    first = []
    waiting = list(pools)
    search_budget = attempt_limit
    while waiting and attempts < search_budget and not cancelled():
        pending = []
        for pool in waiting:
            if attempts >= search_budget or cancelled():
                break
            proposal = pool.popleft()
            value = assess((proposal,))
            if value is not None:
                first.append((proposal, value))
                if len(first) >= 2:
                    search_budget = attempt_limit - 1
            elif pool:
                pending.append(pool)
        waiting = pending

    first.sort(key=lambda item: (item[0].indices, item[0].component_id))
    capacity = limit - 1
    single_count = min(len(first), max(0, capacity - 1))
    result = [value for _, value in first[:single_count]]
    covered = {p.component_id for p, _ in first[:single_count]}
    pairs = sorted(combinations(first, 2), key=lambda pair: (
        sum(p.component_id in covered for p, _ in pair), tuple(p.indices for p, _ in pair)))
    for pair in pairs:
        if attempts >= attempt_limit or cancelled():
            break
        value = assess(tuple(p for p, _ in pair))
        if value is not None:
            result.append(value)
            break
    for _, value in first[single_count:]:
        if len(result) >= capacity:
            break
        result.append(value)
    while len(result) < capacity and any(pools) and attempts < attempt_limit and not cancelled():
        for pool in pools:
            if len(result) >= capacity or attempts >= attempt_limit or cancelled():
                break
            if pool:
                value = assess((pool.popleft(),))
                if value is not None:
                    result.append(value)
    reason = "no more distinct admitted sources"
    if cancelled():
        reason = "cancelled"
    elif len(result) >= capacity:
        reason = "candidate limit"
    elif attempts >= attempt_limit:
        reason = "attempt limit"
    diagnostics.append({"stage": "budget", "attempts": attempts,
                        "attempt_limit": attempt_limit, "requested_candidates": limit,
                        "check_count": sum(d.get("check_count", 0) for d in diagnostics),
                        "retained_candidates": len(result) + 1, "stop_reason": reason})
    return result


def candidate_payloads(payload, row, *, writer, character, profile_hash, limit=None):
    """Validate the optional extension and return primary followed by alternatives."""
    pool = payload.get("candidate_pool")
    if "candidate_pool" not in payload:
        if "candidate_count" in row or (limit is not None and limit > 1):
            raise ValueError("生成产物缺少多候选记录")
        return (payload,)
    if (limit == 1 or not profile_hash or payload.get("source_profile_sha256") != profile_hash
            or payload.get("glyph", {}).get("writer_id") != writer):
        raise ValueError("多候选任务与主字形来源不符")
    if not isinstance(pool, dict) or set(pool) != {"version", "alternatives"} or pool["version"] != POOL_VERSION:
        raise ValueError("不支持的生成候选池协议")
    alternatives = pool["alternatives"]
    count = row.get("candidate_count")
    if (not isinstance(alternatives, list) or type(count) is not int
            or not 1 <= count <= (MAX_CANDIDATES if limit is None else limit)
            or count != len(alternatives) + 1):
        raise ValueError("生成候选数量不符")
    if not alternatives:
        return (payload,)
    primary = payload["glyph"]
    if payload.get("author_only_ready") is not True or primary.get("writer_id") != writer:
        raise ValueError("主字形来源不足或书写者不符")
    fixed_fields = ("schema_version", "character", "writer_id", "codepoint", "locale",
                    "structure_version", "profile_version", "generator")
    target_ids = [(s["standard_stroke_id"], s["order"]) for s in primary["strokes"]]
    seen = {geometry_key(primary)}
    from .assets.glyph_provider import GlyphMetrics, adapt_glyph
    for alt in alternatives:
        if (not isinstance(alt, dict) or not isinstance(alt.get("glyph"), dict)
                or alt.get("candidate_pool") is not None or alt.get("missing") != []
                or alt.get("author_only_ready") is not True
                or alt.get("source_profile_sha256") != profile_hash
                or alt.get("checks") != {"protocol": [], "source_integrity": []}
                or not isinstance(alt.get("variant_admission"), dict)
                or alt["variant_admission"].get("accepted") is not True):
            raise ValueError("额外候选校验或来源记录不完整")
        glyph = alt["glyph"]
        adapt_glyph(glyph, metrics=GlyphMetrics())
        if (any(glyph.get(k) != primary.get(k) for k in fixed_fields)
                or glyph["character"] != character or glyph["writer_id"] != writer
                or [(s["standard_stroke_id"], s["order"]) for s in glyph["strokes"]] != target_ids):
            raise ValueError("额外候选的字形或标准笔画身份不符")
        signature = geometry_key(glyph)
        if signature in seen:
            raise ValueError("生成候选几何重复")
        seen.add(signature)
        provenance, rows = alt.get("provenance"), alt.get("stroke_sources")
        if (not isinstance(provenance, dict) or set(provenance) != {str(i) for i in range(len(target_ids))}
                or not isinstance(rows, list) or len(rows) != len(target_ids)):
            raise ValueError("额外候选的逐笔来源不完整")
        for i, (sid, order) in enumerate(target_ids):
            source = provenance[str(i)]
            if (not isinstance(source, dict) or source.get("kind") not in LABELS
                    or not source.get("character") or source["character"] == character
                    or not source.get("sample_id") or not source.get("source_sha256")
                    or not source.get("source_stroke_id")
                    or rows[i] != {"order": order, "standard_id": sid, **source}):
                raise ValueError("额外候选的逐笔来源不符")
            transform = source.get("transform")
            if (not isinstance(transform, dict) or set(transform) != {"sx", "sy", "tx", "ty"}
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in transform.values())
                    or min(transform["sx"], transform["sy"]) <= 0):
                raise ValueError("额外候选的供体变换无效")
    return (payload, *alternatives)
