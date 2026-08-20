from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path

from .geometry import signature_key
from .samples import iter_index
from .structures import StructureRepository

DEFAULT_COMMON_CHARACTERS = (
    Path(__file__).resolve().parent / "resources" / "common_collection_characters.txt"
)

FEATURE_TARGETS = {
    "component-context": 3,
    "component-identity": 3,
    "component-variant": 2,
    "component-slot": 4,
    "layout": 8,
    "stroke-signature": 3,
}

FEATURE_WEIGHTS = {
    "component-context": 6.0,
    "component-identity": 3.0,
    "component-variant": 2.5,
    "component-slot": 1.5,
    "layout": 1.0,
    "stroke-signature": 0.35,
}

CORE_COMPONENTS = {
    "人",
    "刀",
    "口",
    "囗",
    "土",
    "女",
    "子",
    "心",
    "手",
    "日",
    "月",
    "木",
    "水",
    "火",
    "犬",
    "王",
    "示",
    "禾",
    "竹",
    "糸",
    "艹",
    "衣",
    "言",
    "足",
    "车",
    "辶",
    "金",
    "门",
    "阜/邑",
    "雨",
    "食",
    "马",
    "鸟",
}


def _load_common_characters(path: Path = DEFAULT_COMMON_CHARACTERS) -> list[str]:
    value = Path(path).read_text(encoding="utf-8")
    return list(
        dict.fromkeys(character for character in value if "\u3400" <= character <= "\u9fff")
    )


def _layout(graph) -> str:
    root = next((component for component in graph.components if component.parent_id is None), None)
    return root.layout if root and root.layout else "single"


def _leaf_components(graph) -> list:
    return [
        component
        for component in graph.components
        if component.parent_id is not None
        and not component.children_ids
        and component.glyph_variant != "？"
        and component.stroke_ids
        and component.confidence >= 0.5
    ]


def _graph_features(graph) -> Counter[str]:
    result: Counter[str] = Counter()
    layout = _layout(graph)
    result[f"layout:{layout}"] += 1
    by_id = {component.component_id: component for component in graph.components}
    for component in _leaf_components(graph):
        parent = by_id.get(component.parent_id)
        parent_layout = parent.layout if parent and parent.layout else layout
        result[f"component-identity:{component.canonical}"] += 1
        result[f"component-context:{component.canonical}@{component.role}@{parent_layout}"] += 1
        result[f"component-slot:{component.role}@{parent_layout}"] += 1
        if component.glyph_variant != component.canonical:
            result[
                f"component-variant:{component.glyph_variant}>{component.canonical}@{component.role}"
            ] += 1
    for stroke in graph.strokes:
        result[f"stroke-signature:{signature_key(stroke.signature)}"] += 1
    return result


def _feature_kind(feature: str) -> str:
    return feature.split(":", 1)[0]


def _database_feature_frequencies(
    structures: StructureRepository,
) -> tuple[Counter[str], Counter[str], int]:
    occurrence_frequency: Counter[str] = Counter()
    character_frequency: Counter[str] = Counter()
    characters = structures.characters()
    for character in characters:
        features = _graph_features(structures.get(character))
        occurrence_frequency.update(features)
        character_frequency.update(features.keys())
    return occurrence_frequency, character_frequency, len(characters)


def _target_instances(feature: str, database_frequency: int) -> int:
    kind = _feature_kind(feature)
    target = FEATURE_TARGETS[kind]
    if kind == "component-identity":
        if database_frequency >= 500:
            return max(target, 7)
        if database_frequency >= 150:
            return max(target, 6)
        if database_frequency >= 40:
            return max(target, 5)
    if kind == "component-context":
        if database_frequency >= 200:
            return max(target, 6)
        if database_frequency >= 60:
            return max(target, 5)
        if database_frequency >= 20:
            return max(target, 4)
    if kind == "component-variant" and database_frequency >= 40:
        return max(target, 4)
    return target


def _feature_label(feature: str) -> str:
    kind, value = feature.split(":", 1)
    if kind == "component-context":
        component, role, layout = value.split("@", 2)
        return f"部件“{component}”在{role}/{layout}位置"
    if kind == "component-identity":
        return f"部件“{value}”重复实例"
    if kind == "component-variant":
        return f"变体“{value}”"
    if kind == "component-slot":
        return f"部件槽位 {value}"
    if kind == "layout":
        return f"整字结构 {value}"
    return f"笔画几何 {value}"


def _coverage_summary(counts: Counter[str]) -> dict:
    summary: dict[str, dict[str, int]] = {}
    for kind, target in FEATURE_TARGETS.items():
        values = [count for feature, count in counts.items() if _feature_kind(feature) == kind]
        summary[kind] = {
            "observed": len(values),
            "meeting_target": sum(value >= target for value in values),
            "target_instances": target,
        }
    return summary


def _candidate_score(
    graph,
    features: Counter[str],
    coverage: Counter[str],
    common_rank: int,
    common_count: int,
    database_frequency: Counter[str],
    maximum_frequency: dict[str, int],
) -> tuple[float, list[tuple[float, str]]]:
    contributions: list[tuple[float, str]] = []
    for feature in features:
        kind = _feature_kind(feature)
        frequency = database_frequency[feature]
        target = _target_instances(feature, frequency)
        deficit = max(0, target - coverage[feature])
        if deficit:
            weight = FEATURE_WEIGHTS[kind]
            maximum = max(1, maximum_frequency.get(kind, 1))
            frequency_ratio = math.log1p(frequency) / math.log1p(maximum)
            weight *= 0.65 + frequency_ratio * 1.85
            if kind.startswith("component-") and kind not in {"component-slot"}:
                value = feature.split(":", 1)[1]
                canonical = value.split("@", 1)[0].split(">", 1)[-1]
                identity_frequency = database_frequency[f"component-identity:{canonical}"]
                if canonical not in CORE_COMPONENTS and identity_frequency < 20:
                    weight *= 0.35
            current = coverage[feature]
            progress = 0.45 if current == 0 else (1.5 if current == target - 1 else 1.1)
            contributions.append((weight * progress, feature))
    common_bonus = 2.0 * (1.0 - common_rank / max(common_count, 1))
    effort_penalty = max(0, len(graph.strokes) - 8) * 0.22 + len(graph.strokes) * 0.025
    warning_penalty = min(4.0, len(graph.component_warnings) * 1.5)
    score = sum(value for value, _ in sorted(contributions, reverse=True)[:6])
    return score + common_bonus - effort_penalty - warning_penalty, contributions


def _anchor_recommendations(
    structures: StructureRepository,
    existing: set[str],
    sample_counts: Counter[str],
    *,
    count: int,
    target_repeats: int,
) -> list[dict]:
    candidates: list[tuple[float, int, dict]] = []
    for character in existing:
        if sample_counts[character] >= target_repeats:
            continue
        try:
            graph = structures.get(character)
        except KeyError:
            continue
        leaves = _leaf_components(graph)
        core_count = len({component.canonical for component in leaves} & CORE_COMPONENTS)
        score = core_count * 6.0 + len({component.canonical for component in leaves})
        score += min(len(graph.strokes), 10) * 0.08
        score += 2.0 if _layout(graph) != "single" else 0.0
        score -= max(0, len(graph.strokes) - 10) * 0.3
        score -= len(graph.component_warnings) * 2.0
        candidates.append(
            (
                score,
                ord(character),
                {
                    "character": character,
                    "existing_samples": sample_counts[character],
                    "additional_repeats": target_repeats - sample_counts[character],
                    "target_total_repeats": target_repeats,
                    "layout": _layout(graph),
                    "components": sorted({component.glyph_variant for component in leaves}),
                    "reason": "重复锚点，用于估计部件几何的稳定性",
                },
            )
        )
    candidates.sort(key=lambda value: (-value[0], value[1]))
    return [value[2] for value in candidates[:count]]


def recommend_characters(
    structures: StructureRepository,
    *,
    count: int,
    index_path: Path | None = None,
    profile_path: Path | None = None,
    common_characters_path: Path = DEFAULT_COMMON_CHARACTERS,
    anchor_count: int = 20,
    target_repeats: int = 3,
) -> dict:
    del profile_path  # Component coverage comes from immutable sample character IDs.
    if count < 1:
        raise ValueError("recommendation count must be positive")
    if anchor_count < 0:
        raise ValueError("anchor count cannot be negative")
    if target_repeats < 1:
        raise ValueError("target repeats must be positive")

    samples = list(iter_index(index_path)) if index_path and Path(index_path).is_file() else []
    sample_counts = Counter(sample.character for sample in samples)
    existing = set(sample_counts)
    coverage: Counter[str] = Counter()
    for character in existing:
        try:
            coverage.update(_graph_features(structures.get(character)))
        except KeyError:
            continue
    coverage_before = _coverage_summary(coverage)
    database_occurrences, database_frequency, database_character_count = (
        _database_feature_frequencies(structures)
    )
    maximum_frequency: dict[str, int] = {}
    for feature, frequency in database_frequency.items():
        kind = _feature_kind(feature)
        maximum_frequency[kind] = max(maximum_frequency.get(kind, 0), frequency)

    common_characters = _load_common_characters(common_characters_path)
    candidates: dict[str, tuple[object, Counter[str], int]] = {}
    for rank, character in enumerate(common_characters):
        if character in existing:
            continue
        try:
            graph = structures.get(character)
        except KeyError:
            continue
        if graph.locale != "zh-Hans" or not 2 <= len(graph.strokes) <= 18:
            continue
        if not _leaf_components(graph):
            continue
        candidates[character] = (graph, _graph_features(graph), rank)

    selected: list[dict] = []
    for _ in range(min(count, len(candidates))):
        ranked: list[tuple[float, int, str, list[tuple[float, str]]]] = []
        for character, (graph, features, rank) in candidates.items():
            score, contributions = _candidate_score(
                graph,
                features,
                coverage,
                rank,
                len(common_characters),
                database_frequency,
                maximum_frequency,
            )
            ranked.append((score, rank, character, contributions))
        ranked.sort(key=lambda value: (-value[0], value[1], ord(value[2])))
        score, _, character, contributions = ranked[0]
        graph, features, _ = candidates.pop(character)
        top_contributions = sorted(contributions, reverse=True)[:4]
        top_features = [
            f"{_feature_label(feature)}（结构库覆盖{database_frequency[feature]}字）"
            for _, feature in top_contributions
        ]
        frequency_score = sum(
            database_frequency[feature]
            for _, feature in top_contributions
            if _feature_kind(feature).startswith("component-")
        )
        selected.append(
            {
                "character": character,
                "repeats": 1,
                "score": round(score, 3),
                "layout": _layout(graph),
                "components": sorted(
                    {component.glyph_variant for component in _leaf_components(graph)}
                ),
                "database_frequency_score": frequency_score,
                "reasons": top_features,
            }
        )
        coverage.update(features)

    anchors = _anchor_recommendations(
        structures,
        existing,
        sample_counts,
        count=anchor_count,
        target_repeats=target_repeats,
    )
    new_actions = sum(item["repeats"] for item in selected)
    anchor_actions = sum(item["additional_repeats"] for item in anchors)
    return {
        "schema_version": "component_collection_recommendation_v2",
        "geometry_only": True,
        "frequency_weighted": True,
        "database_character_count": database_character_count,
        "existing_sample_count": len(samples),
        "existing_character_count": len(existing),
        "requested_new_character_count": count,
        "recommended_new_character_count": len(selected),
        "new_characters": "".join(item["character"] for item in selected),
        "recommendations": selected,
        "anchor_count": len(anchors),
        "anchor_characters": "".join(item["character"] for item in anchors),
        "anchors": anchors,
        "collection_action_count": new_actions + anchor_actions,
        "projected_unique_character_count": len(existing) + len(selected),
        "coverage_before": coverage_before,
        "coverage_projected": _coverage_summary(coverage),
        "database_frequency_summary": {
            "top_component_identities": [
                {
                    "component": feature.split(":", 1)[1],
                    "character_frequency": database_frequency[feature],
                    "occurrence_frequency": database_occurrences[feature],
                }
                for feature, _ in sorted(
                    (
                        (feature, frequency)
                        for feature, frequency in database_frequency.items()
                        if _feature_kind(feature) == "component-identity"
                    ),
                    key=lambda item: (-item[1], item[0]),
                )[:100]
            ],
            "top_component_contexts": [
                {
                    "context": feature.split(":", 1)[1],
                    "character_frequency": database_frequency[feature],
                    "occurrence_frequency": database_occurrences[feature],
                }
                for feature, _ in sorted(
                    (
                        (feature, frequency)
                        for feature, frequency in database_frequency.items()
                        if _feature_kind(feature) == "component-context"
                    ),
                    key=lambda item: (-item[1], item[0]),
                )[:100]
            ],
        },
        "common_character_source": str(Path(common_characters_path).resolve()),
    }


def save_recommendations(value: dict, path: Path) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = path.with_name("component_collection.csv")
    text_path = path.with_name("component_characters.txt")
    value = {
        **value,
        "files": {
            "json": str(path.resolve()),
            "collector_csv": str(csv_path.resolve()),
            "character_text": str(text_path.resolve()),
        },
    }
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["character", "repeats", "purpose", "layout", "components", "reason"],
        )
        writer.writeheader()
        for item in value["recommendations"]:
            writer.writerow(
                {
                    "character": item["character"],
                    "repeats": item["repeats"],
                    "purpose": "new_component_context",
                    "layout": item["layout"],
                    "components": " ".join(item["components"]),
                    "reason": "；".join(item["reasons"]),
                }
            )
        for item in value["anchors"]:
            writer.writerow(
                {
                    "character": item["character"],
                    "repeats": item["additional_repeats"],
                    "purpose": "stability_anchor",
                    "layout": item["layout"],
                    "components": " ".join(item["components"]),
                    "reason": item["reason"],
                }
            )
    text_path.write_text(value["new_characters"] + "\n", encoding="utf-8")
    return value
