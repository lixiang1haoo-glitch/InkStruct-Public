"""Application generation orchestration; immutable batches, explicit method identity.

Library/CLI defaults are unchanged. This module owns only the desktop workflow.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .samples import sha256_file

METHODS = {"v62": "v6.2 exp（推荐）", "v61": "v6.1 exp", "v4": "v4 adaptive"}
VERSION = "desktop-corrected-v61-20261014.1"
V62_VERSION = "desktop-semantic-v62-20261020.1"


def workflow_version(method):
    return V62_VERSION if method == 'v62' else VERSION


def resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def identity():
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]


def corrections():
    root = resources()
    return [root / "third_party/makemeahanzi/graphics.txt",
            root / "third_party/makemeahanzi/dictionary.txt",
            root / "configs/structure_overrides/unclipped_reference_v1.json"]


def code_hashes():
    root = Path(__file__).parent
    # Frozen distributions include these exact source files for dependency identity.
    return {p.name: sha256_file(p) for p in sorted(root.glob("*.py")) if p.stem not in {"train", "model", "dataset"}}


class GenerationWorkflow:
    def __init__(self, workspace, database):
        self.workspace, self.database = Path(workspace), Path(database)
        self.root = self.workspace / "generation"

    def state_path(self, writer, source):
        import hashlib
        self.validate_writer(writer)
        key = hashlib.sha256(str(Path(source).resolve()).encode()).hexdigest()[:24]
        return self.root / "states" / writer / (key + ".json")

    @staticmethod
    def validate_writer(writer):
        if not re.fullmatch(r"[\w-]{1,64}", writer, re.UNICODE):
            raise ValueError("作者 ID 请使用 1–64 个文字、数字、下划线或连字符。")

    def state(self, writer, source):
        path = self.state_path(writer, source)
        return read(path) if path.is_file() else {}

    def readiness(self, writer, source, method):
        result = {"import": False, "profile": False, "generate": False}
        try:
            self.validate_writer(writer)
            if method not in METHODS:
                raise ValueError("请选择生成方式。")
            if not source or not Path(source).is_dir():
                raise ValueError("请选择该作者的单字采集 JSON 目录，然后导入。")
            result["import"] = True
            if not self.database.is_file():
                raise ValueError("结构库缺失，请重新安装完整应用。")
            if method in ("v61", "v62") and not all(p.is_file() for p in corrections()):
                raise ValueError("参考修正资源缺失，请重新安装完整应用。")
            state = self.state(writer, source)
            batch = state.get("import", {})
            if not batch.get("accepted_count") or not Path(batch.get("index", "")).is_file():
                raise ValueError("尚未导入可用的汉字样本。请先点“1. 导入”；字母和符号可直接在字体库加入。")
            result["profile"] = True
            profile = state.get("profiles", {}).get(method, {})
            if profile.get("index_sha256") != batch["index_sha256"] or not Path(profile.get("path", "")).is_file():
                raise ValueError("样本已导入；请点“2. 建档”，准备所选方法需要的档案。")
            if profile.get("workflow_version") != workflow_version(method):
                raise ValueError("生成流程已更新，请重新建档。旧档案会保留。")
            result["generate"] = True
            result["message"] = f"已就绪 · {batch['accepted_count']} 份样本 · {METHODS[method]}"
        except (ValueError, OSError, KeyError) as error:
            result["message"] = str(error)
        return result

    def require(self, operation, writer, source, method):
        ready = self.readiness(writer, source, method)
        if not ready[operation]:
            raise ValueError(ready["message"])

    def import_samples(self, writer, source, method="v61"):
        from .samples import import_samples
        self.require("import", writer, source, method)
        report = import_samples(Path(source), writer, self.root / "imports" / identity())
        if report["accepted_count"] == 0:
            raise ValueError("没有可导入的该作者汉字样本。请核对作者 ID 和目录；支持 handwriting_single_v1，符号请在字体库加入。导入记录：" + str(Path(report['index']).parent))
        state = self.state(writer, source)
        state["import"] = report
        state["profiles"] = {}  # Old immutable files stay on disk; no stale profile reuse.
        write(self.state_path(writer, source), state)
        return {"message": f"导入 {report['accepted_count']} 份样本；跳过 {report['rejected_count']} 个文件。", "report": str(Path(report['index']).with_name('import_report.json'))}

    def build_profile(self, writer, source, method):
        from .profile import build_profile
        from .structures import StructureRepository
        self.require("profile", writer, source, method)
        state = self.state(writer, source)
        batch = state["import"]
        if sha256_file(Path(batch["index"])) != batch["index_sha256"]:
            raise ValueError("导入样本索引已改变，请重新导入后建档。")
        profile, path = build_profile(writer, Path(batch["index"]), StructureRepository(self.database),
                                      self.root / "profiles" / identity(),
                                      retain_source_trajectories=method in ("v61", "v62"))
        if not profile.sample_count or (method in ("v61", "v62") and not profile.source_trajectories):
            raise ValueError("没有可用于此方法的可靠笔画映射。请检查建档排除记录或补充标准笔序汉字样本。档案：" + str(path))
        record = {"path": str(path), "sha256": sha256_file(path), "method": method,
                  "index_sha256": batch["index_sha256"], "workflow_version": workflow_version(method),
                  "database_sha256": sha256_file(self.database), "source_samples": len(profile.source_trajectories)}
        write(path.with_name("application-build.json"), record)
        state.setdefault("profiles", {})[method] = record
        write(self.state_path(writer, source), state)
        return {"message": f"建档完成：{profile.sample_count} 份，{profile.character_count} 字；完整来源轨迹 {len(profile.source_trajectories)} 份。", "profile": str(path)}

    def generate(self, writer, source, method, text, *, all_supported=False, progress=None, cancelled=lambda: False,
                 workers='auto', targets=None):
        from .structures import StructureRepository
        self.require("generate", writer, source, method)
        state = self.state(writer, source)
        profile = state["profiles"][method]
        if sha256_file(Path(profile["path"])) != profile["sha256"] or sha256_file(self.database) != profile["database_sha256"]:
            raise ValueError("档案或结构库已改变，请重新建档。")
        if sha256_file(Path(state["import"]["index"])) != profile["index_sha256"]:
            raise ValueError("导入索引已改变，请重新导入并建档。")
        repository = StructureRepository(self.database)
        from .generation_targets import target_manifest, validate_targets
        supported = repository.characters()
        manifest = target_manifest(''.join(supported) if all_supported else text, supported,
                                   source={'kind': 'all-supported'} if all_supported else None)
        if targets is not None and not all_supported:
            if targets.get('source', {}).get('kind') == 'builtin-character-sets':
                from .character_sets import CharacterSets
                CharacterSets().validate(targets, supported)
            validate_targets(targets)
            if targets['requested'] != manifest['requested']:
                raise ValueError('字表已改变，请重新确认生成目标')
            manifest = {**targets, 'supported': manifest['supported'], 'unsupported': manifest['unsupported']}
        validate_targets(manifest)
        requested = manifest['requested']
        run_id = identity()
        if method == "v4":
            from .generate import generate_run
            result, output = generate_run(writer, requested, repository, Path(profile["path"]),
                output_root=self.root / "outputs", run_id=run_id, png=False,
                component_conditioning="adaptive", component_strength=1.0, trajectory_mode="legacy",
                progress_callback=progress, cancelled=cancelled)
            application_manifest = {"method": "v4 adaptive", "version": VERSION, "engine": result.get("generator"),
                        "fixed_config": {"component_mode": "adaptive", "component_strength": 1., "trajectory_mode": "legacy"},
                        "profile": profile, "code": code_hashes(), "source_status": "unknown: v4 has no exact per-stroke author provenance"}
            write(output / "application-generation.json", application_manifest)
            write(output / 'target-manifest.json', manifest)
        else:
            output = self.root / "outputs" / run_id
            result = generate_v61(output, writer, requested, repository, profile, progress, cancelled,
                                  semantic=method == 'v62', workers=workers, target_manifest=manifest)
        return {**result, "writer": writer, "output": str(output), "message": f"{METHODS[method]}：完成 {result['completed_count']} 字，失败 {result['failed_count']} 字。结果已保存，可送入字体库。"}


def generate_v61(output, writer, characters, base, profile_record, progress, cancelled, *, semantic=False,
                 workers="auto", target_manifest=None):
    from .generation_parallel import run_generation
    return run_generation(output, writer, characters, base, profile_record, progress, cancelled,
                          semantic=semantic, workers=workers, target_manifest=target_manifest)


def prepare_generation(writer, base, profile_record, *, semantic=False, reference_paths=None, cancelled=lambda: False):
    from .exemplar_index import component_key
    from .generation_v61_helpers import (
        check_sources,
        compact_sources,
        hybrid,
        plan_sources,
        source_audit,
    )
    from .positional_variants import FAMILIES
    from .positional_variants import PARAMETERS as variant_parameters
    from .profile import load_profile
    from .reuse_rules import RULES
    from .reuse_rules import VERSION as rule_version
    from .structure_corrections import CorrectedStructureRepository
    from .trajectory_experiment import invariants
    from .v61_author_strokes import PARAMETERS
    from .v61_author_strokes_batch import BatchAuthorStrokeFallback
    from .v61_candidate_expansion import CandidateExpansionGenerator, ExpansionPolicy

    generator_class, stroke_class = CandidateExpansionGenerator, BatchAuthorStrokeFallback
    version, method = VERSION, 'v6.1 exp'
    if semantic:
        from .v62_exp import SemanticBatchStrokeFallback, SemanticCandidateGenerator
        generator_class, stroke_class = SemanticCandidateGenerator, SemanticBatchStrokeFallback
        version, method = V62_VERSION, 'v6.2 exp'

    if cancelled():
        raise InterruptedError("生成已取消")
    target = CorrectedStructureRepository(base, *(reference_paths or corrections()))
    if cancelled():
        raise InterruptedError("生成已取消")
    profile = load_profile(Path(profile_record["path"]))
    engine = generator_class(profile, base, target, split_rules=True)
    if cancelled():
        raise InterruptedError("生成已取消")
    single = stroke_class(profile, base)
    policy = ExpansionPolicy(context=True, hierarchy=True, nested=True, whole_target=True, anisotropic=True)
    engine.inventory(True)
    protocol = {"name": method + " corrected desktop generation", "method": method, "version": version,
        "writers": [writer], "characters": [], "requested_characters": [],
        "generation_mode": "cross_character_generation", "same_character_sources_excluded": True,
        "profile": profile_record, "inputs": {str(p): sha256_file(Path(p)) for p in [base.path, *(reference_paths or corrections())]},
        "code": code_hashes(), "component_policy": asdict(policy), "rule_version": rule_version, "rules": RULES,
        "parameters": PARAMETERS, "position_families": FAMILIES, "position_parameters": variant_parameters,
        "pipeline": "corrected reference; source-aware complete components; guarded expansion; bounded sheep-key replacement; author stroke fallback; explicit reference gaps",
        "key_replacement_scope": "same verified sheep sixth-stroke rule only; freshly selected plans, no private reviewed result dependency",
        "reviewed_plans": "historical writer-specific frozen placements are not applied to newly built archives",
        "status": "running"}
    if semantic:
        from .v62_semantics import PARAMETERS as semantic_parameters
        from .v62_semantics import VERSION as semantic_version
        protocol['semantic_admission'] = {'version': semantic_version, 'parameters': semantic_parameters,
            'scope': 'stop-component keys and vertical bend hooks; other content forms not newly verified',
            'source_ink': 'unchanged vertices, pressure and within-stroke timing',
            'unknown': 'registered ambiguous critical forms reject candidate; unrelated unregistered forms retain v6.1 behavior'}
    protocol["initialization_rule_log"] = engine.rule_log
    engine.rule_log = []
    count = 0

    def compute(character, output):
        nonlocal count
        output = Path(output)
        folder = output / writer
        folder.mkdir(parents=True, exist_ok=True)
        stem = folder / f"{ord(character):04X}"
        row = {"writer": writer, "character": character, "files": {}, "warnings": [], "same_character_reuse": False}
        try:
            ctx = engine.prepare(character)
            plan = ctx.baseline_plan
            logs = {}
            if semantic:
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
                old = CandidateExpansionGenerator(profile, base, target, split_rules=True, variant_checks=False)
                oc = old.prepare(character)
                _, op, _ = old.expand(oc, oc.baseline_plan, existing_pool=True)
                _, op, _ = old.expand(oc, op, root_contexts=roots)
                oc, _, op, _ = old.extend(oc, op, policy)
                audit = [{"target_component": p.component_id, "evidence": engine.variant_evidence(oc, p)} for p in op.values()]
                record = {"old_selected_audit": audit, "arms": {"old_G": {"provenance": [asdict(p) for p in op.values()]}}}
                glyph, sources, logs["hybrid"] = hybrid(single, record, glyph, ctx.graph,
                                                        [s.median for s in ctx.graph.strokes], sources)
            glyph, sources, fill = single.fill(glyph, ctx.graph, [s.median for s in ctx.graph.strokes], sources)
            if semantic:
                evidence = [engine.variant_evidence(ctx, p) for p in plan.values()]
                if any(not v['accepted'] for v in evidence):
                    raise ValueError('v6.2 final component semantic audit failed')
                logs['semantic_final_components'] = evidence
            glyph.generator = method.replace(' ', '-') + ":" + version
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
            path = stem.with_suffix(".json.gz")
            path.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(), mtime=0))
            row["files"][str(path.relative_to(output))] = sha256_file(path)
        except Exception as error:  # noqa: BLE001 - isolate glyph failures; never publish invalid geometry
            row.update(status="failed", error=f"{type(error).__name__}: {error}")
        write(stem.with_suffix(".json"), row)
        engine.rule_log = []
        count += 1
        if count % 100 == 0:
            target._cache.clear()
            engine._rule_graphs = {k: v for k, v in engine._rule_graphs.items() if k[0] == "source"}
        return row

    return protocol, compute


