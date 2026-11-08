"""Author-scoped inputs and a preflight inventory for font publication."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from unicodedata import category

from ..punctuation import capture_character
from ..symbol_tasks import TASK_GROUPS


GROUPS = {
    **{key: label for key, (label, _, _) in TASK_GROUPS.items()},
    "latin_unspecified": "英文（旧录制，未注明正斜体）",
    "other": "其他扩展字符",
}


def symbol_group(character, style="unspecified"):
    character = capture_character(character)
    for key, (_, characters, declared_style) in TASK_GROUPS.items():
        if character in characters and (declared_style == "unspecified" or style == declared_style):
            return key
    if character in TASK_GROUPS["latin_upright"][1]:
        return "latin_unspecified"
    return "punctuation" if category(character).startswith("P") else "other"


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
    "generated": "生成字形", "recorded": "独立录制", "shared": "中英文共用",
    "reuse": "已确认复用", "constructed": "规则合成",
}


def batch_info(run, writer):
    from .importer import _read

    root = Path(run)
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
                    "reuse" if "confirmed_reuse" in summary else
                    "shared" if "shared_punctuation" in summary else "recorded")
        coverage[group, kind, char] += 1
    return coverage


CONSTRUCTION_DETAILS = {
    "no-qualified-minus-source": "缺少合格的录制减号",
    "no-qualified-recorded-source": "缺少合格录制来源",
    "source-not-qualified-recorded-ink": "来源未达到录制笔迹条件",
    "degenerate-source-or-minus-not-single-stroke": "来源尺寸无效或减号并非单笔",
    "minus-has-no-horizontal-extent": "减号没有水平长度",
}


def review_selection(writer, run, symbols, name, groups=None):
    from ..capture_management import valid_writer
    from ..generation_variants import MAX_CANDIDATES
    from .importer import _read, build_font

    if not valid_writer(writer):
        raise ValueError("请先选择书写者")
    batch = batch_info(run, writer) if run else None
    if batch and (not batch["characters"] or batch["status"] in {"running", "preparing", "failed"}):
        raise ValueError("该批次没有可入包的已完成字形，或仍在生成")
    diagnostics = []
    records, provenance = build_font(None, writer=writer, name=name, symbols=symbols,
                                     symbol_groups=groups, diagnostics=diagnostics)
    coverage = candidate_coverage(records, provenance)
    if batch and (groups is None or "han" in groups):
        for char in batch["characters"]:
            count = 1
            if batch["has_pool"]:
                row = _read(batch["path"] / writer / f"{ord(char):04X}.json")
                count = row.get("candidate_count", 1)
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
    return {"coverage": coverage, "issues": issues, "batch": batch}


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
