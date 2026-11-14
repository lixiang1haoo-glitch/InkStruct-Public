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

METHODS = {"v63": "v6.3 exp（支持连笔）", "v62": "v6.2 exp", "v61": "v6.1 exp", "v4": "v4 adaptive",
           "v631": "v6.3.1（支持连笔）"}
VERSION = "desktop-corrected-v61-20261014.1"
V62_VERSION = "desktop-semantic-v62-20261020.1"
V63_VERSION = "desktop-connected-v63-2"
CONNECTED_METHODS = {"v63", "v631"}
MULTI_CANDIDATE_METHODS = {"v62", *CONNECTED_METHODS}
SOURCE_METHODS = {"v61", *MULTI_CANDIDATE_METHODS}


def workflow_version(method):
    if method == "v631":
        # v6.3.1 preserves the layout of both split and connected profiles.
        return V63_VERSION
    return {"v62": V62_VERSION, "v63": V63_VERSION}.get(method, VERSION)


def profile_for_method(profiles, method):
    if method == "v631":
        return profiles.get("v631") or profiles.get("v63", {})
    return profiles.get(method, {})


def connected_profile_valid(profile):
    record = profile.get("connected", {})
    path = Path(record.get("path", ""))
    return path.is_file() and sha256_file(path) == record.get("sha256")


def resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def identity():
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]


def corrections(root=None):
    root = root or resources()
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
        from .capture_management import valid_writer

        if not valid_writer(writer) and not re.fullmatch(r"[\w-]{1,64}", writer, re.UNICODE):
            raise ValueError("请选择有效的书写者，或填写已有作者 ID。")

    def state(self, writer, source):
        path = self.state_path(writer, source)
        return read(path) if path.is_file() else {}

    def sample_status(self, writer, source, method, previous=None):
        from .samples import iter_index, sample_identity, scan_samples

        self.validate_writer(writer)
        source = Path(source).resolve()
        if not source.is_dir():
            raise ValueError("样本目录不存在")
        state = self.state(writer, source)
        batch = state.get("import", {})
        profile = profile_for_method(state.get("profiles", {}), method)
        index = Path(batch.get("index", ""))
        stamp = []
        for path in sorted(source.rglob("*.json")):
            stat = path.stat()
            stamp.append((path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        key = (writer, source, method, batch.get("index"), batch.get("created_at"),
               profile.get("path"), index.is_file(), Path(profile.get("path", "")).is_file(), stamp)
        if previous and previous["key"] == key:
            return previous
        samples, _, foreign = scan_samples(source, writer)
        imported = batch.get("accepted_count", 0)
        indexed = set(map(sample_identity, iter_index(index))) if index.is_file() else set()
        donors = None
        if profile.get("index_sha256") == batch.get("index_sha256") and Path(profile.get("path", "")).is_file():
            if method in ("v61", "v62"):
                donors = profile.get("source_samples")
            elif "effective_donors" in profile:
                donors = profile["effective_donors"]
            else:
                from .profile import load_profile
                donors = load_profile(Path(profile["path"])).sample_count
        records = [str(value) for value in (batch.get("index"), profile.get("path")) if value]
        connected = profile.get("connected")
        if connected:
            records.append(connected["path"])
        return {"key": key, "path": str(source), "foreign": foreign, "found": len(samples), "records": records,
                "imported": imported, "imported_at": batch.get("created_at"), "donors": donors,
                "connected": connected,
                "changed": bool(imported) and indexed != set(map(sample_identity, samples))}

    def readiness(self, writer, source, method):
        result = {"import": False, "profile": False, "generate": False, "start": False}
        try:
            self.validate_writer(writer)
            if method not in METHODS:
                raise ValueError("请选择生成方式。")
            if not source or not Path(source).is_dir():
                raise ValueError("请选择该作者的单字采集 JSON 目录。")
            result["import"] = True
            if not self.database.is_file():
                raise ValueError("结构库缺失，请重新安装完整应用。")
            if method in SOURCE_METHODS and not all(p.is_file() for p in corrections()):
                raise ValueError("参考修正资源缺失，请重新安装完整应用。")
            result["start"] = True
            state = self.state(writer, source)
            batch = state.get("import", {})
            if not batch.get("accepted_count") or not Path(batch.get("index", "")).is_file():
                raise ValueError("尚未导入可用的汉字样本。开始生成时自动导入并建档。")
            result["profile"] = True
            profile = profile_for_method(state.get("profiles", {}), method)
            if profile.get("index_sha256") != batch["index_sha256"] or not Path(profile.get("path", "")).is_file():
                raise ValueError("样本已导入。开始生成时会为所选方法建立档案。")
            if profile.get("workflow_version") != workflow_version(method):
                raise ValueError("生成流程已更新。开始生成时会重新建档。")
            result["generate"] = True
            result["message"] = f"已就绪 · {batch['accepted_count']} 份样本 · {METHODS[method]}"
        except (ValueError, OSError, KeyError) as error:
            result["message"] = str(error)
        return result

    def require(self, operation, writer, source, method):
        ready = self.readiness(writer, source, method)
        if not ready[operation]:
            raise ValueError(ready["message"])

    def _import_batch(self, writer, source, method):
        from .samples import import_samples
        self.require("import", writer, source, method)
        report = import_samples(Path(source), writer, self.root / "imports" / identity(), require_single_writer=True)
        return self._checked_import(report)

    @staticmethod
    def _checked_import(report):
        if report["accepted_count"] == 0:
            raise ValueError("没有可导入的该作者汉字样本。请核对作者 ID 和目录；支持 handwriting_single_v1，符号请在字体库加入。导入记录：" + str(Path(report['index']).parent))
        return report

    def prepare_profile(self, writer, source, method, notify, cancelled):
        from .samples import iter_index, sample_identity, scan_samples, write_sample_index

        if cancelled():
            return None
        notify("核对样本", "检查当前目录、作者归属及已有档案")
        source = Path(source).resolve()
        samples, rejected, foreign = scan_samples(source, writer)
        if cancelled():
            return None
        if foreign:
            raise ValueError(f"样本目录包含其他书写者：{'、'.join(foreign)}。请选择仅属于 {writer} 的目录。")
        state = self.state(writer, source)
        batch = state.get("import", {})
        profiles = state.get("profiles", {})
        index = Path(batch.get("index", ""))
        reusable = (samples and batch.get("accepted_count") == len(samples) and index.is_file()
                    and sha256_file(index) == batch.get("index_sha256")
                    and set(map(sample_identity, iter_index(index))) == set(map(sample_identity, samples)))
        if reusable:
            profile = profile_for_method(profiles, method)
            path = Path(profile.get("path", ""))
            if (profile.get("index_sha256") == batch["index_sha256"]
                    and profile.get("workflow_version") == workflow_version(method)
                    and path.is_file() and sha256_file(path) == profile.get("sha256")
                    and sha256_file(self.database) == profile.get("database_sha256")
                    and (method not in CONNECTED_METHODS or connected_profile_valid(profile))):
                notify("沿用档案", str(path))
                return profile
        else:
            notify("导入样本", f"校验通过 {len(samples)} 份，跳过 {len(rejected)} 个文件")
            batch = self._checked_import(write_sample_index(
                source, writer, self.root / "imports" / identity(), samples, rejected))
            profiles = {}
        if cancelled():
            return None
        notify("建档", f"使用 {batch['accepted_count']} 份已导入样本")
        profile, result = self._build_profile(writer, method, batch)
        if cancelled():
            return None
        if self.state(writer, source) != state:
            raise ValueError("当前样本记录已被另一窗口更新，请重新开始生成。")
        write(self.state_path(writer, source), {**state, "import": batch, "profiles": {**profiles, method: profile}})
        notify("建档完成", result["message"] + " " + result["profile"])
        return profile

    def import_samples(self, writer, source, method="v61"):
        report = self._import_batch(writer, source, method)
        write(self.state_path(writer, source), {"import": report, "profiles": {}})
        return {"message": f"导入 {report['accepted_count']} 份样本；跳过 {report['rejected_count']} 个文件。", "report": str(Path(report['index']).with_name('import_report.json'))}

    def build_profile(self, writer, source, method):
        self.require("profile", writer, source, method)
        state = self.state(writer, source)
        record, result = self._build_profile(writer, method, state["import"])
        state.setdefault("profiles", {})[method] = record
        write(self.state_path(writer, source), state)
        return result

    def update_samples(self, writer, source, method):
        batch = self._import_batch(writer, source, method)
        record, result = self._build_profile(writer, method, batch)
        write(self.state_path(writer, source), {"import": batch, "profiles": {method: record}})
        result["report"] = str(Path(batch["index"]).with_name("import_report.json"))
        return result

    def _build_profile(self, writer, method, batch):
        from .profile import build_profile
        from .structures import StructureRepository
        if sha256_file(Path(batch["index"])) != batch["index_sha256"]:
            raise ValueError("导入样本索引已改变，请重新导入后建档。")
        repo = StructureRepository(self.database)
        index = Path(batch["index"])
        profile, path = build_profile(writer, index, repo,
                                      self.root / "profiles" / identity(),
                                      retain_source_trajectories=method in SOURCE_METHODS)
        connected = None
        if method in CONNECTED_METHODS:
            if method == "v631":
                from .v631.connected import build_connected_profile
            else:
                from .v63 import build_connected_profile
            connected = build_connected_profile(writer, index, repo, profile, path)
        donors = len(profile.source_trajectories) if method in SOURCE_METHODS else profile.sample_count
        donors += connected["samples"] if connected else 0
        if not donors:
            raise ValueError("没有可用于此方法的可靠笔画映射。请检查建档排除记录或补充标准笔序汉字样本。档案：" + str(path))
        record = {"path": str(path), "sha256": sha256_file(path), "method": method,
                  "index_sha256": batch["index_sha256"], "workflow_version": workflow_version(method),
                  "database_sha256": sha256_file(self.database), "source_samples": len(profile.source_trajectories),
                  "effective_donors": donors}
        if connected is not None:
            record["connected"] = connected
        write(path.with_name("application-build.json"), record)
        return record, {"message": f"建档完成：{profile.sample_count} 份，{profile.character_count} 字；有效供体 {record['effective_donors']} 份。", "profile": str(path)}

    def generate(self, writer, source, method, text, *, all_supported=False, progress=None, cancelled=lambda: False,
                 workers='auto', targets=None, candidate_limit=None, preparation=None, same_character=None,
                 source_score=False, diversity_score=False):
        from .generation_variants import DEFAULT_CANDIDATES, candidate_attempt_limit
        from .structures import StructureRepository
        if candidate_limit is None:
            candidate_limit = DEFAULT_CANDIDATES if method in MULTI_CANDIDATE_METHODS else 1
        candidate_attempt_limit(candidate_limit)
        if method not in MULTI_CANDIDATE_METHODS and candidate_limit != 1:
            raise ValueError('v6.2 和 v6.3 系列支持同字多候选，其他方法每字保留一份。')
        if same_character is None:
            same_character = method in CONNECTED_METHODS
        if same_character and method not in CONNECTED_METHODS:
            raise ValueError("只有 v6.3 系列支持同字原稿回放。")
        if source_score and method == "v4":
            raise ValueError("v4 缺少逐笔来源记录，无法计算来源分。")
        self.require("start" if preparation is not None else "generate", writer, source, method)
        repository = StructureRepository(self.database)
        from .generation_targets import structure_targets, target_manifest, validate_targets
        supported = repository.characters()
        manifest = structure_targets(supported) if all_supported else target_manifest(text, supported)
        if targets is not None and not all_supported:
            if targets.get('source', {}).get('kind') == 'builtin-character-sets':
                from .character_sets import CharacterSets
                CharacterSets().validate(targets, supported)
            if targets.get('source', {}).get('kind') == 'all-supported' and targets != structure_targets(supported):
                raise ValueError('结构库完整字表已变化，请重新选择内置字表')
            validate_targets(targets)
            if targets['requested'] != manifest['requested']:
                raise ValueError('字表已改变，请重新确认生成目标')
            manifest = {**targets, 'supported': manifest['supported'], 'unsupported': manifest['unsupported']}
        validate_targets(manifest)
        requested = manifest['requested']
        if preparation is not None:
            profile = self.prepare_profile(writer, source, method, preparation, cancelled)
            if profile is None or cancelled():
                return {"status": "cancelled", "writer": writer, "completed_count": 0, "failed_count": 0,
                        "requested_count": len(requested), "message": "已取消生成，尚未生成字形。"}
            preparation("生成字形", f"目标 {len(requested)} 字")
        else:
            state = self.state(writer, source)
            profile = profile_for_method(state["profiles"], method)
            if sha256_file(Path(profile["path"])) != profile["sha256"] or sha256_file(self.database) != profile["database_sha256"]:
                raise ValueError("档案或结构库已改变，请重新建档。")
            if sha256_file(Path(state["import"]["index"])) != profile["index_sha256"]:
                raise ValueError("导入索引已改变，请重新导入并建档。")
            if method == "v631" and not connected_profile_valid(profile):
                raise ValueError("连笔档案已改变，请重新建档。")
        started_at = datetime.now(UTC).isoformat()
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
            completed_characters = result.get("completed_characters", "")
        else:
            output = self.root / "outputs" / run_id
            if method == "v631":
                from .generation_parallel import run_generation

                result = run_generation(output, writer, requested, repository, profile, progress, cancelled,
                                        semantic=True, workers=workers, target_manifest=manifest,
                                        candidate_limit=candidate_limit, same_character=same_character,
                                        engine="v631")
            else:
                result = generate_v61(output, writer, requested, repository, profile, progress, cancelled,
                                      semantic=method in MULTI_CANDIDATE_METHODS, workers=workers, target_manifest=manifest,
                                      candidate_limit=candidate_limit, same_character=same_character)
            completed_characters = result.get("completed_preview", "")
        if source_score or diversity_score:
            from .generation_scores import evaluate

            if preparation is not None:
                preparation("计算生成指标", "按本次目标字和可选字形统计")
            scores = evaluate(output, writer, requested, source=source_score, diversity=diversity_score,
                              completed=result['completed_count'])
            result['scores'] = scores
            write(output / 'generation-scores.json', scores)
        variants = result.get("variant_character_count", 0)
        note = f"其中 {variants} 字有多份可用字形。" if variants else ""
        status = "已取消，保留已完成部分。 " if result.get("status") == "cancelled" else ""
        return {**result, "requested_count": len(requested), "writer": writer, "output": str(output),
                "started_at": started_at, "completed_preview": "".join(completed_characters[:24]),
                "message": f"{METHODS[method]} · {status}完成 {result['completed_count']}/{len(requested)} 字，"
                           f"失败 {result['failed_count']} 字。{note}结果已保存，可送入字体库。"}


def generate_v61(output, writer, characters, base, profile_record, progress, cancelled, *, semantic=False,
                 workers="auto", target_manifest=None, candidate_limit=1, same_character=False):
    from .generation_parallel import run_generation
    return run_generation(output, writer, characters, base, profile_record, progress, cancelled,
                          semantic=semantic, workers=workers, target_manifest=target_manifest,
                          candidate_limit=candidate_limit, same_character=same_character)


def prepare_generation(writer, base, profile_record, *, semantic=False, reference_paths=None,
                       cancelled=lambda: False, candidate_limit=1, same_character=False):
    from .exemplar_index import component_key
    from .generation_v61_helpers import (
        check_sources,
        compact_sources,
        hybrid,
        plan_sources,
        source_audit,
    )
    from .generation_variants import (
        MAX_CANDIDATES,
        POOL_VERSION,
        SELECTION_POLICY,
        alternative_candidates,
        candidate_attempt_limit,
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
    if type(candidate_limit) is not int or not 1 <= candidate_limit <= (MAX_CANDIDATES if semantic else 1):
        raise ValueError("无效的生成候选数量")
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
    connected = profile_record.get("connected")
    units = []
    split_by_character, whole_by_character = {}, {}
    if connected is not None:
        from .v63 import ARCHIVE, CONNECTED_METHOD, connected_candidates, same_character_candidates
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
    if connected is not None:
        protocol.update(method=CONNECTED_METHOD, version=V63_VERSION,
                        connected_candidates={"same_character": same_character, "limit": candidate_limit},
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
