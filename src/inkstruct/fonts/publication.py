"""Author-scoped inputs and a preflight inventory for font publication."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from ..punctuation import SHARED_PUNCTUATION
from ..symbol_catalog import SYMBOL_GROUPS, symbol_group
from .publication_rules import PublicationRules, RuleEvidence, RuleRow


GROUPS = {
    **{key: label for key, (label, _, _) in SYMBOL_GROUPS.items()},
    "latin_unspecified": "英文 · 写法未标注",
    "other": "未归类的已有字符",
}


def symbol_input(path, writer):
    """A collector root can contain several writers. A ZIP is an explicit input."""
    from ..capture_management import valid_writer

    path = Path(path)
    samples = path / "samples" / writer
    return samples if valid_writer(writer) and samples.is_dir() else path


STATUS = {
    "completed": "已完成", "complete": "已完成", "completed_with_errors": "部分完成（有失败）",
    "cancelled": "已取消（保留已完成部分）", "running": "生成中", "preparing": "准备中",
    "failed": "失败", "legacy": "历史批次",
}

COVERAGE = {
    "generated": "生成字形", "recorded": "独立录制", "shared": "同形共用",
    "constructed": "规则合成",
}


def batch_info(run, writer):
    from .importer import _read

    root = Path(run)
    grouped = root / "v63-run.json"
    if grouped.is_file():
        from ..v63 import RUN
        data = _read(grouped)
        if data.get("schema_version") != RUN or data.get("writer") != writer:
            raise ValueError("连笔批次协议或书写者不符")
        completed = tuple(data["files"])
        failed = [{"character": char, "reason": reason} for char, reason in data["failed"].items()]
        date = (datetime.fromisoformat(data["created_at"]).astimezone() if "created_at" in data
                else datetime.fromtimestamp(grouped.stat().st_mtime).astimezone())
        requested = data.get("requested", (*completed, *data["failed"]))
        return {"path": root, "characters": completed, "target": len(requested),
                "date": date, "method": "v6.3 exp", "status": "failed" if not completed else
                "completed_with_errors" if failed else "completed",
                "protocol": True, "failed": failed, "pending": [], "has_pool": False}
    protocol = (root / "protocol.json").is_file()
    manifest = root / ("protocol.json" if protocol else "manifest.json")
    if not manifest.is_file() and (root / "trajectories").is_dir():
        paths = sorted((root / "trajectories").glob("U+*.json"))
        rows = [_read(path) for path in paths]
        if any(row.get("writer_id") != writer for row in rows):
            raise ValueError("生成结果书写者不一致")
        data = {"writer_id": writer, "completed_characters": [row["character"] for row in rows]}
        manifest = root
    else:
        data = _read(manifest)
    if protocol:
        if writer not in data.get("writers", ()):
            raise ValueError("生成批次不属于该书写者")
        completed = data["characters"]
        requested = data.get("requested_characters", completed)
        method = data.get("method") or data.get("name") or "历史生成"
        pending = data.get("pending", [])
    else:
        if data.get("writer_id") != writer:
            raise ValueError("生成批次不属于该书写者")
        completed = data.get("completed_characters", "")
        requested = data.get("requested_count", len(completed))
        method = "v4 adaptive" if data.get("component_mode") == "adaptive" else data.get("generator", "历史生成")
        pending = []
        if data.get("status") == "cancelled" and (root / "target-manifest.json").is_file():
            targets = _read(root / "target-manifest.json")["requested"]
            attempted = {*completed, *(item["character"] for item in data.get("failed", []))}
            pending = [char for char in targets if char not in attempted]
    status = data.get("status", "legacy")
    date = data.get("started_at") or data.get("created_at")
    if date:
        date = datetime.fromisoformat(date.replace("Z", "+00:00")).astimezone()
    else:
        try:
            date = datetime.strptime(root.name.split("-")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).astimezone()
        except ValueError:
            date = datetime.fromtimestamp(manifest.stat().st_mtime).astimezone()
    target = requested if isinstance(requested, int) else len(requested)
    return {"path": root, "characters": tuple(completed), "target": target, "date": date,
            "method": method, "status": status, "protocol": protocol,
            "failed": data.get("failed", []), "pending": pending,
            "has_pool": "candidate_pool" in data}


def batch_label(info):
    return (f"{info['date']:%Y-%m-%d %H:%M} · {info['method']} · {len(info['characters'])}/{info['target']} 字"
            f" · {STATUS.get(info['status'], info['status'])}")


def generated_batches(root, writer):
    root = Path(root)
    batches = []
    for folder in {*root.glob("*"), *(root / writer).glob("*")}:
        if not folder.is_dir():
            continue
        try:
            info = batch_info(folder, writer)
            if info["characters"] and info["status"] not in {"running", "preparing", "failed"}:
                batches.append(info)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    for info in sorted(batches, key=lambda item: (item["date"], item["path"].name), reverse=True):
        yield batch_label(info), info["path"]


def publication_stamp(writer, run, symbols):
    """Identify reviewed inputs, including sample moves and task configuration edits."""
    from .library import fingerprint

    files = set()
    if run:
        root = Path(run)
        files.add(root)
        files.update(path for path in root.rglob("*.json") if path.is_file())
        files.update(root.rglob("*.json.gz"))
    if symbols:
        root = Path(symbols)
        files.add(root)
        if root.is_dir():
            files.update(symbol_input(root, writer).rglob("*.json"))
            files.update(root.rglob("state.json"))
    return tuple((path, fingerprint(path)) for path in sorted(files))


class PublicationInputsChanged(ValueError):
    pass


def require_publication_stamp(writer, run, symbols, stamp):
    try:
        current = publication_stamp(writer, run, symbols)
    except OSError:
        current = None
    if stamp != current:
        raise PublicationInputsChanged("批次、样本或复用配置已变化，请重新核对待制包清单。")


def candidate_coverage(records, provenance):
    coverage = Counter()
    for record in records:
        summary = provenance[record["candidate_id"]]
        char = record["character"]
        if summary["source_kind"] in {"generated", "composed"} and "symbol_construction" not in summary:
            group, kind = "han", "generated"
        else:
            group = symbol_group(char, record["letter_style"])
            kind = ("constructed" if "symbol_construction" in summary else
                    "reuse" if "confirmed_reuse" in summary or "mapped_reuse" in summary else
                    "shared" if "shared_punctuation" in summary else "recorded")
        coverage[group, kind, char] += 1
    return coverage


def display_coverage(coverage):
    merged = Counter()
    for (group, origin, char), count in coverage.items():
        merged[group, "shared" if origin == "reuse" else origin, char] += count
    return merged


CONSTRUCTION_DETAILS = {
    "no-qualified-minus-source": "缺少合格的录制减号",
    "no-qualified-recorded-source": "缺少合格录制来源",
    "source-not-qualified-recorded-ink": "来源未达到录制笔迹条件",
    "degenerate-source-or-minus-not-single-stroke": "来源尺寸无效或减号并非单笔",
    "minus-has-no-horizontal-extent": "减号没有水平长度",
}

CONSTRUCTION_SOURCES = {
    "–": "数学减号 −",
    "～": "双笔约等号 ≈（取其中一笔）",
    "℃": "句号 。与英文正体 C",
    "*": "单笔数学减号 −",
    "∗": "单笔数学减号 −",
    "∶": "全角冒号 ：或半角冒号 :",
    "∘": "句号 。",
    "ℏ": "录制小写 h 与单笔 − 或 -",
}


def rule_rows(coverage, groups, evidence, issues, has_symbols, rules=PublicationRules()):
    from ..symbol_reuse import reuse_options

    def selected(group):
        return groups is None or group in groups

    def outcome(group, target, kind):
        if not selected(group):
            return "目标类别未勾选"
        if coverage[group, "recorded", target]:
            return "独立录制优先"
        if count := coverage[group, kind, target]:
            return f"已共用 {count} 份" if kind in {"shared", "reuse"} else f"已合成 {count} 份"
        if not has_symbols:
            return "尚未选择扩展来源"
        reasons = dict.fromkeys(item["reason"] for item in issues
                                if item["group"] == group and item["target"] == target)
        return "；".join(reasons) if reasons else "缺少可用供体"

    rows = []
    for full, half in SHARED_PUNCTUATION.items():
        group = symbol_group(full)
        key = "shared", full
        enabled = rules.allows(key)
        active = [f"{target} ← {source} · {coverage[group, 'shared', target]} 份"
                  for target, source in ((full, half), (half, full)) if coverage[group, "shared", target]]
        if selected(group) and all(coverage[group, "recorded", c] for c in (full, half)):
            result = "两边均有独立录制"
        elif not enabled:
            result = "本次停用"
        elif active:
            result = "已共用 · " + "；".join(active)
        else:
            result = outcome(group, full if not coverage[group, "recorded", full] else half, "shared")
        rows.append(RuleRow(key, "同形共用", f"{full} ↔ {half}", "任一侧的有效独立录制", "—", enabled, result))
    selected_donors = {choice.target for choice in rules.donors}
    for group, target, source in reuse_options():
        key = group, target
        confirmed = key in evidence.confirmed
        enabled = rules.allows(key, confirmed=confirmed)
        label = "英文斜体" if group == "latin_italic" else "希腊字母"
        result = outcome(group, target, "reuse")
        if not enabled and not coverage[group, "recorded", target]:
            result = "本次停用"
        donor_status = "本次指定" if key in selected_donors else "采集任务已指定" if confirmed else "自动选择"
        rows.append(RuleRow(key, "同形共用", f"{target}（{label}）", f"{source}（英文正体）",
                            donor_status, enabled, result, source))
    for target, sources in CONSTRUCTION_SOURCES.items():
        key = "constructed", target
        enabled = rules.allows(key)
        result = outcome(symbol_group(target), target, "constructed")
        if not enabled and not coverage[symbol_group(target), "recorded", target]:
            result = "本次停用"
        rows.append(RuleRow(key, "规则合成", target, sources, "—", enabled, result))
    return rows


def review_selection(writer, run, symbols, name, groups=None, *, rules=PublicationRules()):
    from ..capture_management import valid_writer
    from ..generation_variants import MAX_CANDIDATES
    from .importer import _read, build_font

    if not valid_writer(writer):
        raise ValueError("请先选择书写者")
    batch = batch_info(run, writer) if run else None
    if batch and (not batch["characters"] or batch["status"] in {"running", "preparing", "failed"}):
        raise ValueError("该批次没有可入包的已完成字形，或仍在生成")
    diagnostics = []
    evidence = RuleEvidence()
    records, provenance = build_font(None, writer=writer, name=name, symbols=symbols,
                                     symbol_groups=groups, diagnostics=diagnostics,
                                     rules=rules, rule_evidence=evidence)
    coverage = candidate_coverage(records, provenance)
    if batch and (groups is None or "han" in groups):
        for char in batch["characters"]:
            count = 1
            if batch["has_pool"]:
                row = _read(batch["path"] / writer / f"{ord(char):04X}.json")
                count = row.get("total_candidate_count", row.get("candidate_count", 1))
                if type(count) is not int or not 1 <= count <= MAX_CANDIDATES:
                    raise ValueError("汉字候选数量无效：" + char)
            coverage["han", "generated", char] += count
    issues = []
    for item in diagnostics:
        for char in item["target"].split("/") if item["target"] != "/" else ("/",):
            group = item.get("group") or symbol_group(char)
            if groups is not None and group not in groups:
                continue
            if not symbols:
                continue
            reason = CONSTRUCTION_DETAILS.get(item["reason"], item["reason"])
            if item["reason"] == "no-qualified-recorded-source":
                reason += "（冒号 : / ：）" if char == "∶" else "（中文句号 。）"
            issues.append({**item, "group": group, "target": char, "reason": reason})
    return {"coverage": coverage, "issues": issues, "batch": batch, "rule_evidence": evidence,
            "rules": rule_rows(coverage, groups, evidence, issues, bool(symbols), rules)}


def publication_inventory(writer, run, symbols):
    """Compatibility inventory for callers using the original per-group sets."""
    data = review_selection(writer, run, symbols, "")
    han, recorded, rejected, reused = set(), defaultdict(set), defaultdict(set), defaultdict(set)
    for group, kind, char in data["coverage"]:
        if group == "han":
            han.add(char)
        elif kind == "reuse":
            reused[group].add(char)
        elif kind in {"shared", "recorded"}:
            recorded[group].add(char)
    for issue in data["issues"]:
        if issue.get("invalid"):
            rejected[issue["group"]].add(issue["target"])
    return han, recorded, rejected, reused
