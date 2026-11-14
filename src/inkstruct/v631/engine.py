"""Desktop generation using only the v6.3.1 donor policies."""

import gzip
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import sys

from ..generation_workflow import code_hashes, connected_profile_valid, corrections, read, write
from ..samples import sha256_file

ENGINE_VERSION = "desktop-connected-v631-1"


def implementation_hashes():
    result = code_hashes()
    root = (Path(sys._MEIPASS) / "inkstruct/v631" if getattr(sys, "frozen", False)
            else Path(__file__).parent)
    files = sorted(root.glob("*.py"))
    if not (root / "engine.py").is_file():
        raise ValueError("v6.3.1 实现源码清单缺失")
    return result | {f"v631/{p.name}": sha256_file(p) for p in files}


def prepare_generation(writer, base, profile_record, *, reference_paths=None,
                       cancelled=lambda: False, candidate_limit=1, same_character=False):
    from .component_index import component_key
    from .provenance import (
        check_sources,
        compact_sources,
        hybrid,
        plan_sources,
        source_audit,
    )
    from .alternatives import (
        MAX_CANDIDATES,
        POOL_VERSION,
        SELECTION_POLICY,
        alternative_candidates,
        candidate_attempt_limit,
    )
    from .position_rules import FAMILIES
    from .position_rules import PARAMETERS as variant_parameters
    from ..profile import load_profile
    from .reuse_rules import RULES
    from .reuse_rules import VERSION as rule_version
    from ..structure_corrections import CorrectedStructureRepository
    from ..trajectory_experiment import invariants
    from .stroke_sources import PARAMETERS
    from .components import ComponentSearch, ExpansionPolicy
    from .semantics import SemanticComponentSearch, SemanticStrokePlacement

    if type(candidate_limit) is not int or not 1 <= candidate_limit <= MAX_CANDIDATES:
        raise ValueError("无效的生成候选数量")
    if cancelled():
        raise InterruptedError("生成已取消")
    target = CorrectedStructureRepository(base, *(reference_paths or corrections()))
    if cancelled():
        raise InterruptedError("生成已取消")
    profile = load_profile(Path(profile_record["path"]))
    if profile.writer_id != writer or sha256_file(Path(profile_record["path"])) != profile_record["sha256"]:
        raise ValueError("分笔档案作者或摘要不符")
    connected = profile_record.get("connected")
    if not connected or not connected_profile_valid(profile_record):
        raise ValueError("缺少可验证的连笔档案")
    split_by_character, whole_by_character = {}, {}
    from .connected import ARCHIVE, CONNECTED_METHOD, connected_candidates, same_character_candidates
    archive = read(connected["path"])
    if archive.get("schema_version") != ARCHIVE or archive.get("writer") != writer:
        raise ValueError("连笔档案格式或作者不符")
    units = archive["units"]
    if same_character:
        for sample in profile.source_trajectories.values():
            split_by_character.setdefault(sample.character, []).append(sample)
        for unit in units:
            if unit["path"] == "whole":
                whole_by_character.setdefault(unit["character"], []).append(unit)
    engine = SemanticComponentSearch(profile, base, target, split_rules=True)
    if cancelled():
        raise InterruptedError("生成已取消")
    single = SemanticStrokePlacement(profile, base)
    policy = ExpansionPolicy(context=True, hierarchy=True, nested=True, whole_target=True, anisotropic=True)
    engine.inventory(True)
    protocol = {"name": "v6.3.1 corrected desktop generation", "method": CONNECTED_METHOD, "version": ENGINE_VERSION,
        "writers": [writer], "characters": [], "requested_characters": [],
        "generation_mode": "cross_character_generation", "same_character_sources_excluded": True,
        "profile": profile_record, "inputs": {str(p): sha256_file(Path(p)) for p in [base.path, *(reference_paths or corrections())]},
        "code": implementation_hashes(), "component_policy": asdict(policy), "rule_version": rule_version, "rules": RULES,
        "parameters": PARAMETERS, "position_families": FAMILIES, "position_parameters": variant_parameters,
        "pipeline": "corrected reference; source-aware complete components; guarded expansion; bounded sheep-key replacement; author stroke fallback; explicit reference gaps",
        "key_replacement_scope": "same verified sheep sixth-stroke rule only; freshly selected plans, no private reviewed result dependency",
        "reviewed_plans": "historical writer-specific frozen placements are not applied to newly built archives",
        "status": "running"}
    from .content_rules import PARAMETERS as semantic_parameters
    from .content_rules import VERSION as semantic_version
    protocol['semantic_admission'] = {'version': semantic_version, 'parameters': semantic_parameters,
        'scope': 'stop-component keys and vertical bend hooks; other content forms not newly verified',
        'source_ink': 'unchanged vertices, pressure and within-stroke timing',
        'unknown': 'registered ambiguous critical forms reject candidate; unrelated unregistered forms retain v6.1 behavior'}
    protocol.update(connected_candidates={"same_character": same_character, "limit": candidate_limit},
                    same_character_sources_excluded=not same_character)
    if candidate_limit > 1:
        protocol["candidate_pool"] = {"version": POOL_VERSION, "limit": candidate_limit,
                                      "attempt_limit": candidate_attempt_limit(candidate_limit),
                                      "selection": SELECTION_POLICY}
    protocol["initialization_rule_log"] = engine.rule_log
    engine.rule_log = []
    count = 0

    def save_payload(output, stem, row, payload):
        path = stem.with_suffix(".json.gz")
        path.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(), mtime=0))
        row["files"][str(path.relative_to(output))] = sha256_file(path)

    def save_replays(output, stem, row, replays, *, cross_error=None):
        n = len(replays)
        checks = {"protocol": [], "source_integrity": []}
        standard = replays[0]["standard_slots"]
        row.update(status="complete", strokes=len(standard), source_strokes=len(standard), reference_strokes=0,
                   missing=[], same_character_reuse=True, connected_count=n, total_candidate_count=n,
                   checks=checks, author_only_ready=True)
        payload = {"replay_only": True, "connected_candidates": replays, "standard_slots": standard,
                   "source_profile_sha256": profile_record["sha256"], "checks": checks}
        if cross_error is not None:
            payload["cross_character_error"] = f"{type(cross_error).__name__}: {cross_error}"
        save_payload(output, stem, row, payload)
        write(stem.with_suffix(".json"), row)
        return row

    def compute(character, output):
        nonlocal count
        output = Path(output)
        folder = output / writer
        folder.mkdir(parents=True, exist_ok=True)
        stem = folder / f"{ord(character):04X}"
        identity = {"writer": writer, "character": character}
        row = {**identity, "files": {}, "warnings": [], "same_character_reuse": False}
        replays = []
        try:
            if character in split_by_character or character in whole_by_character:
                replays = same_character_candidates(writer, base.get(character), split_by_character.get(character, ()),
                                                    whole_by_character.get(character, ()), limit=candidate_limit,
                                                    cancelled=cancelled)
                if len(replays) == candidate_limit:
                    return save_replays(output, stem, row, replays)
            ctx = engine.prepare(character)
            plan = ctx.baseline_plan
            logs = {}
            logs['semantic_initial_removals'] = engine.semantic_log
            _, plan, logs["existing_pool"] = engine.expand(ctx, plan, existing_pool=True)
            roots = sorted({component_key(ctx.graph, n) for n in ctx.graph.components if n.path != "root" and len(n.stroke_ids) >= 2})
            _, plan, logs["whole_root"] = engine.expand(ctx, plan, root_contexts=roots)
            ctx, glyph, plan, logs["expansion"] = engine.extend(ctx, plan, policy)
            sources = plan_sources([asdict(p) for p in plan.values()])
            source_audit(engine, ctx.graph, sources)
            # The historical hybrid rule is bounded to sheep's sixth stroke. Rebuild
            # its candidate evidence from THIS archive, never read another author's results.
            if any(n.canonical == "羊" for n in ctx.graph.components):
                old = ComponentSearch(profile, base, target, split_rules=True, variant_checks=False)
                oc = old.prepare(character)
                _, op, _ = old.expand(oc, oc.baseline_plan, existing_pool=True)
                _, op, _ = old.expand(oc, op, root_contexts=roots)
                oc, _, op, _ = old.extend(oc, op, policy)
                audit = [{"target_component": p.component_id, "evidence": engine.variant_evidence(oc, p)} for p in op.values()]
                record = {"old_selected_audit": audit, "arms": {"old_G": {"provenance": [asdict(p) for p in op.values()]}}}
                glyph, sources, logs["hybrid"] = hybrid(single, record, glyph, ctx.graph,
                                                        [s.median for s in ctx.graph.strokes], sources)
            glyph, sources, fill = single.fill(glyph, ctx.graph, [s.median for s in ctx.graph.strokes], sources)
            evidence = [engine.variant_evidence(ctx, p) for p in plan.values()]
            if any(not v['accepted'] for v in evidence):
                raise ValueError('v6.3.1 final component semantic audit failed')
            logs['semantic_final_components'] = evidence
            glyph.generator = CONNECTED_METHOD + ":" + ENGINE_VERSION
            checks = {"protocol": invariants(glyph, ctx.graph), "source_integrity": check_sources(profile, glyph, sources)}
            if any(checks.values()):
                raise ValueError("生成协议或来源完整性校验失败，未发布此字。")
            rows, donors, gaps = compact_sources(ctx.graph, sources, fill["trials"])
            if gaps:
                row["warnings"].append(f"含 {len(gaps)} 笔参考替代；字体应用时将汇总提示。")
            row.update(status="warning" if gaps else "complete", strokes=len(glyph.strokes),
                source_strokes=len(sources), reference_strokes=len(gaps), missing=gaps,
                source_kinds=dict(Counter(p["kind"] for p in sources.values())), donors=donors,
                checks=checks, author_only_ready=not gaps, stroke_sources=rows)
            payload = {"glyph": asdict(glyph), "provenance": sources, "stroke_sources": rows, "logs": logs,
                "fallback": fill, "rule_log": engine.rule_log, "checks": checks, "missing": gaps,
                "author_only_ready": not gaps, "source_profile_sha256": profile_record["sha256"],
                "structure_correction": target.events.get(character), "reference_identity": target.identity}
            remaining = candidate_limit - len(replays)
            if candidate_limit > 1:
                logs["variant_trials"] = []
                alternatives = alternative_candidates(engine, ctx, glyph, plan, sources,
                                                      limit=remaining, cancelled=cancelled,
                                                      diagnostics=logs["variant_trials"])
                for candidate in alternatives:
                    candidate["source_profile_sha256"] = profile_record["sha256"]
                payload["candidate_pool"] = {"version": POOL_VERSION, "alternatives": alternatives}
                row["candidate_count"] = 1 + len(alternatives)
            groups = replays
            if units and (remaining > 1 or candidate_limit == 1):
                groups = replays + connected_candidates(
                    writer, base.get(character), ctx.graph, payload["glyph"], rows, units, base,
                    same_character=False, limit=max(1, remaining - row.get("candidate_count", 1)),
                    cancelled=cancelled)
            if groups:
                if candidate_limit > 1:
                    del alternatives[max(0, candidate_limit - len(groups) - 1):]
                    row["candidate_count"] = 1 + len(alternatives)
                payload["connected_candidates"] = groups
                row["connected_count"] = len(groups)
                row["total_candidate_count"] = len(groups) + (row.get("candidate_count", 1) if candidate_limit > 1 else 0)
                row["same_character_reuse"] = bool(replays)
            save_payload(output, stem, row, payload)
        except Exception as error:  # noqa: BLE001 - isolate glyph failures; never publish invalid geometry
            if replays and not isinstance(error, OSError):
                engine.rule_log = []
                return save_replays(output, stem, {**identity, "warnings": [], "files": {}}, replays, cross_error=error)
            row.update(status="failed", error=f"{type(error).__name__}: {error}")
        write(stem.with_suffix(".json"), row)
        engine.rule_log = []
        count += 1
        if count % 100 == 0:
            target._cache.clear()
            engine._rule_graphs = {k: v for k, v in engine._rule_graphs.items() if k[0] == "source"}
        return row

    return protocol, compute
