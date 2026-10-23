from __future__ import annotations

import csv
import heapq
import json
import math
from collections import Counter
from itertools import pairwise
from pathlib import Path

from .component_style import component_context_key, component_trajectory_key
from .geometry import signature_key
from .samples import iter_index
from .schemas import StyleProfile
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

TARGET_COVERAGE_WEIGHTS = {
    "stroke-signature": 0.20,
    "component-identity": 0.15,
    "component-context": 0.25,
    "component-trajectory": 0.30,
    "layout": 0.10,
}

DEFAULT_TARGET_COVERAGE_THRESHOLDS = (90.0, 95.0, 99.0, 99.9, 100.0)


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


def _information_gain_score(
    graph,
    features: Counter[str],
    coverage: Counter[str],
    database_frequency: Counter[str],
    uncertainty_scale: float,
) -> tuple[float, list[tuple[float, str]]]:
    contributions: list[tuple[float, str]] = []
    relevant = {
        "component-context",
        "component-identity",
        "component-slot",
        "layout",
        "stroke-signature",
    }
    for feature, instances in features.items():
        kind = _feature_kind(feature)
        if kind not in relevant:
            continue
        precision = 1.0 + coverage[feature]
        variance_before = uncertainty_scale / precision
        variance_after = uncertainty_scale / (precision + instances)
        prevalence = 1.0 + math.log1p(database_frequency[feature])
        gain = FEATURE_WEIGHTS[kind] * prevalence * (variance_before - variance_after)
        contributions.append((gain, feature))
    stroke_cost = 1.0 + 0.035 * len(graph.strokes) ** 1.15
    warning_cost = 1.0 + 0.25 * len(graph.component_warnings)
    return sum(value for value, _ in contributions) / (stroke_cost * warning_cost), contributions


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
    strategy: str = "coverage",
) -> dict:
    if strategy not in {"coverage", "information-gain"}:
        raise ValueError(f"unknown recommendation strategy: {strategy}")
    if count < 1:
        raise ValueError("recommendation count must be positive")
    if anchor_count < 0:
        raise ValueError("anchor count cannot be negative")
    if target_repeats < 1:
        raise ValueError("target repeats must be positive")

    uncertainty_scale = 1.0
    if profile_path and Path(profile_path).is_file():
        from .profile import load_profile

        profile = load_profile(profile_path)
        if profile.factorized_style is not None:
            uncertainty_scale = max(
                0.05,
                float(
                    profile.factorized_style.uncertainty_summary.get("latent_std_mean", 1.0)
                ),
            )

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
            if strategy == "information-gain":
                score, contributions = _information_gain_score(
                    graph,
                    features,
                    coverage,
                    database_frequency,
                    uncertainty_scale,
                )
            else:
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
        "schema_version": (
            "component_collection_recommendation_v3"
            if strategy == "information-gain"
            else "component_collection_recommendation_v2"
        ),
        "geometry_only": True,
        "frequency_weighted": strategy == "coverage",
        "selection_strategy": strategy,
        "posterior_uncertainty_scale": uncertainty_scale,
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


def accepted_profile_characters(index_path: Path, profile: StyleProfile) -> set[str]:
    """Return characters contributing at least one non-excluded sample to a profile."""
    excluded_ids = {item["sample_id"] for item in profile.excluded_samples}
    return {
        sample.character
        for sample in iter_index(index_path)
        if sample.sample_id not in excluded_ids
    }


def _target_coverage_features(graph) -> dict[str, set[str]]:
    features = {kind: set() for kind in TARGET_COVERAGE_WEIGHTS}
    features["layout"].add(_layout(graph))
    for stroke in graph.strokes:
        features["stroke-signature"].add(signature_key(stroke.signature))
    for component in _leaf_components(graph):
        features["component-identity"].add(component.canonical)
        features["component-context"].add(component_context_key(graph, component))
        if len(component.stroke_ids) >= 2:
            features["component-trajectory"].add(
                component_trajectory_key(graph, component)
            )
    return features


def _profile_target_coverage_features(
    profile: StyleProfile,
    structures: StructureRepository,
    accepted_characters: set[str],
) -> dict[str, set[str]]:
    layouts = set()
    for character in accepted_characters:
        try:
            layouts.add(_layout(structures.get(character)))
        except KeyError:
            continue
    return {
        "stroke-signature": {prototype.signature for prototype in profile.prototypes.values()},
        "component-identity": {
            prototype.canonical for prototype in profile.component_layouts.values()
        },
        "component-context": set(profile.component_layouts),
        "component-trajectory": set(profile.component_trajectories),
        "layout": layouts,
    }


def _target_coverage_score(
    covered_mass: dict[str, int], target_mass: dict[str, int]
) -> float:
    active_weight = sum(
        TARGET_COVERAGE_WEIGHTS[kind]
        for kind in TARGET_COVERAGE_WEIGHTS
        if target_mass[kind] > 0
    )
    return 100.0 / max(active_weight, 1e-12) * sum(
        TARGET_COVERAGE_WEIGHTS[kind]
        * covered_mass[kind]
        / target_mass[kind]
        for kind in TARGET_COVERAGE_WEIGHTS
        if target_mass[kind] > 0
    )


def greedy_marginal_order(candidates, gain, tie_key):
    """Shared lazy weighted-set-cover order; caller updates coverage after each yield.

    Gains must be nonnegative and nonincreasing as coverage grows. Keeping the
    tie key explicit preserves the legacy planner's exact order while allowing
    an experimental collection budget to use the same selection mechanism.
    """
    heap = [(-gain(c), tie_key(c), c) for c in candidates]
    heapq.heapify(heap)
    while heap:
        negative_gain, tie, character = heapq.heappop(heap)
        actual_gain = gain(character)
        if abs(actual_gain + negative_gain) > 1e-12:
            heapq.heappush(heap, (-actual_gain, tie, character))
            continue
        if actual_gain <= 1e-15:
            return
        yield character


def plan_target_coverage_tiers(
    structures: StructureRepository,
    profile: StyleProfile,
    *,
    accepted_characters: set[str],
    sampled_characters: set[str] | None = None,
    target_characters: list[str] | None = None,
    candidate_characters: set[str] | None = None,
    thresholds: tuple[float, ...] = DEFAULT_TARGET_COVERAGE_THRESHOLDS,
) -> dict:
    """Plan nested, target-conditioned collection tiers with few unique characters.

    The score is a projected structural coverage score.  It assumes each new
    sample passes alignment and profile extraction; pressure, timing and model
    quality must be measured again after collection.
    """
    if not thresholds or any(not 0.0 < value <= 100.0 for value in thresholds):
        raise ValueError("coverage thresholds must be inside (0, 100]")
    if any(left >= right for left, right in pairwise(thresholds)):
        raise ValueError("coverage thresholds must be strictly increasing")

    all_characters = structures.characters()
    all_character_set = set(all_characters)
    target = list(dict.fromkeys(target_characters or all_characters))
    unsupported = [character for character in target if character not in all_character_set]
    if unsupported:
        raise ValueError(f"unsupported target characters: {''.join(unsupported[:20])}")
    if candidate_characters is not None:
        unsupported_candidates = candidate_characters - all_character_set
        if unsupported_candidates:
            raise ValueError(
                "unsupported candidate characters: "
                + "".join(sorted(unsupported_candidates)[:20])
            )

    target_set = set(target)
    feature_totals = {kind: Counter() for kind in TARGET_COVERAGE_WEIGHTS}
    candidate_features: dict[str, dict[str, set[str]]] = {}
    candidate_metadata: dict[str, dict] = {}
    for graph in structures.iter_graphs():
        features = _target_coverage_features(graph)
        candidate_features[graph.character] = features
        candidate_metadata[graph.character] = {
            "layout": _layout(graph),
            "components": sorted(
                {component.glyph_variant for component in _leaf_components(graph)}
            ),
            "stroke_count": len(graph.strokes),
        }
        if graph.character not in target_set:
            continue
        for kind, values in features.items():
            if kind == "stroke-signature":
                for stroke in graph.strokes:
                    feature_totals[kind][signature_key(stroke.signature)] += 1
            elif kind == "layout":
                feature_totals[kind][_layout(graph)] += 1
            else:
                for component in _leaf_components(graph):
                    if kind == "component-identity":
                        feature_totals[kind][component.canonical] += 1
                    elif kind == "component-context":
                        feature_totals[kind][component_context_key(graph, component)] += 1
                    elif kind == "component-trajectory" and len(component.stroke_ids) >= 2:
                        feature_totals[kind][component_trajectory_key(graph, component)] += 1

    target_mass = {
        kind: sum(counts.values()) for kind, counts in feature_totals.items()
    }
    observed_initial = _profile_target_coverage_features(
        profile, structures, accepted_characters
    )
    observed = {kind: set(values) for kind, values in observed_initial.items()}
    covered_mass = {
        kind: sum(
            count
            for feature, count in feature_totals[kind].items()
            if feature in observed[kind]
        )
        for kind in TARGET_COVERAGE_WEIGHTS
    }
    baseline_covered_mass = dict(covered_mass)
    baseline_score = _target_coverage_score(covered_mass, target_mass)
    active_weight = sum(
        TARGET_COVERAGE_WEIGHTS[kind]
        for kind in TARGET_COVERAGE_WEIGHTS
        if target_mass[kind] > 0
    )

    def candidate_gain(character: str) -> float:
        return 100.0 / max(active_weight, 1e-12) * sum(
            TARGET_COVERAGE_WEIGHTS[kind]
            * sum(
                feature_totals[kind][feature]
                for feature in candidate_features[character][kind]
                if feature not in observed[kind]
            )
            / max(1, target_mass[kind])
            for kind in TARGET_COVERAGE_WEIGHTS
        )

    selected: list[str] = []
    selected_set: set[str] = set()
    tier_assignments: dict[str, int] = {}
    tier_summaries: list[dict] = []
    candidate_universe = (
        set(candidate_features)
        if candidate_characters is None
        else set(candidate_characters)
    )
    candidate_pool = candidate_universe - accepted_characters
    for tier, threshold in enumerate(thresholds, start=1):
        phase: list[str] = []
        order = greedy_marginal_order(
            candidate_pool - selected_set, candidate_gain,
            lambda c: (candidate_metadata[c]["stroke_count"], ord(c)),
        )
        while _target_coverage_score(covered_mass, target_mass) + 1e-10 < threshold:
            try:
                character = next(order)
            except StopIteration as exc:
                raise RuntimeError(f"target coverage score {threshold} is unreachable") from exc
            selected.append(character)
            selected_set.add(character)
            phase.append(character)
            for kind, values in candidate_features[character].items():
                for feature in values:
                    if feature not in observed[kind]:
                        observed[kind].add(feature)
                        covered_mass[kind] += feature_totals[kind][feature]

        support = {kind: Counter() for kind in TARGET_COVERAGE_WEIGHTS}
        for character in selected:
            for kind, values in candidate_features[character].items():
                support[kind].update(values)
        removed = 0
        for character in reversed(phase):
            loss = sum(
                100.0
                / max(active_weight, 1e-12)
                * TARGET_COVERAGE_WEIGHTS[kind]
                * feature_totals[kind][feature]
                / max(1, target_mass[kind])
                for kind, values in candidate_features[character].items()
                for feature in values
                if feature not in observed_initial[kind] and support[kind][feature] == 1
            )
            if (
                _target_coverage_score(covered_mass, target_mass) - loss + 1e-10
                < threshold
            ):
                continue
            selected.remove(character)
            selected_set.remove(character)
            phase.remove(character)
            removed += 1
            for kind, values in candidate_features[character].items():
                for feature in values:
                    support[kind][feature] -= 1
                    if (
                        feature not in observed_initial[kind]
                        and support[kind][feature] == 0
                    ):
                        observed[kind].remove(feature)
                        covered_mass[kind] -= feature_totals[kind][feature]

        for character in phase:
            tier_assignments[character] = tier
        tier_summaries.append(
            {
                "tier": tier,
                "target_score": threshold,
                "projected_score": _target_coverage_score(covered_mass, target_mass),
                "added_character_count": len(phase),
                "cumulative_character_count": len(selected),
                "redundant_characters_removed": removed,
                "dimension_scores": {
                    kind: (
                        100.0 * covered_mass[kind] / target_mass[kind]
                        if target_mass[kind] > 0
                        else 100.0
                    )
                    for kind in TARGET_COVERAGE_WEIGHTS
                },
            }
        )

    replay_observed = {
        kind: set(values) for kind, values in observed_initial.items()
    }
    replay_mass = {
        kind: sum(
            count
            for feature, count in feature_totals[kind].items()
            if feature in replay_observed[kind]
        )
        for kind in TARGET_COVERAGE_WEIGHTS
    }
    sampled_characters = sampled_characters or accepted_characters
    recommendations = []
    for sequence, character in enumerate(selected, start=1):
        contributions = []
        for kind, values in candidate_features[character].items():
            for feature in values:
                if feature in replay_observed[kind]:
                    continue
                contribution = (
                    100.0
                    / max(active_weight, 1e-12)
                    * TARGET_COVERAGE_WEIGHTS[kind]
                    * feature_totals[kind][feature]
                    / max(1, target_mass[kind])
                )
                contributions.append((contribution, kind, feature))
                replay_observed[kind].add(feature)
                replay_mass[kind] += feature_totals[kind][feature]
        contributions.sort(reverse=True)
        metadata = candidate_metadata[character]
        recommendations.append(
            {
                "character": character,
                "repeats": 1,
                "purpose": (
                    "quality_rerecord"
                    if character in sampled_characters
                    else "target_coverage"
                ),
                "tier": tier_assignments[character],
                "target_score": thresholds[tier_assignments[character] - 1],
                "sequence": sequence,
                "projected_score_after": _target_coverage_score(
                    replay_mass, target_mass
                ),
                "layout": metadata["layout"],
                "components": metadata["components"],
                "stroke_count": metadata["stroke_count"],
                "reasons": [
                    f"{kind}:{feature}（目标集中出现{feature_totals[kind][feature]}次）"
                    for _, kind, feature in contributions[:4]
                ],
            }
        )

    return {
        "schema_version": "target_collection_tiers_v1",
        "writer_id": profile.writer_id,
        "profile_version": profile.profile_version,
        "profile_source_index_sha256": profile.source_index_sha256,
        "structure_metadata": {
            key: value
            for key, value in structures.metadata().items()
            if not key.endswith("_path")
        },
        "target_character_count": len(target),
        "candidate_character_count": len(candidate_universe),
        "target_feature_mass": target_mass,
        "existing_valid_character_count": len(accepted_characters),
        "existing_valid_target_character_count": len(
            accepted_characters & target_set
        ),
        "baseline_projected_score": baseline_score,
        "baseline_dimension_scores": {
            kind: (
                100.0 * baseline_covered_mass[kind] / target_mass[kind]
                if target_mass[kind] > 0
                else 100.0
            )
            for kind in TARGET_COVERAGE_WEIGHTS
        },
        "score_kind": "projected_structural_target_coverage",
        "score_weights": TARGET_COVERAGE_WEIGHTS,
        "score_assumption": (
            "Each recommended sample passes alignment and profile extraction; actual dynamic "
            "and uncertainty scores must be recomputed after collection."
        ),
        "selection_method": "greedy_weighted_set_cover_with_backward_redundancy_elimination",
        "global_minimum_guaranteed": False,
        "locally_irredundant_by_tier": True,
        "tiers": tier_summaries,
        "recommended_character_count": len(recommendations),
        "recommendations": recommendations,
    }


def save_target_coverage_tiers(value: dict, path: Path) -> dict:
    """Save one audit CSV and five incremental collector-compatible CSV files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    master_path = path.with_name("target_coverage_tiers.csv")
    fieldnames = [
        "character",
        "repeats",
        "purpose",
        "tier",
        "target_score",
        "sequence",
        "projected_score_after",
        "stroke_count",
        "layout",
        "components",
        "reason",
    ]
    with master_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for item in value["recommendations"]:
            writer.writerow(
                {
                    **{key: item[key] for key in fieldnames if key in item},
                    "projected_score_after": f'{item["projected_score_after"]:.6f}',
                    "components": " ".join(item["components"]),
                    "reason": "；".join(item["reasons"]),
                }
            )

    incremental_paths = []
    collector_fields = ["character", "repeats", "purpose", "layout", "components", "reason"]
    for tier in value["tiers"]:
        target_label = str(tier["target_score"]).replace(".", "_")
        tier_path = path.with_name(f'tier_{tier["tier"]}_to_{target_label}.csv')
        with tier_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=collector_fields)
            writer.writeheader()
            for item in value["recommendations"]:
                if item["tier"] != tier["tier"]:
                    continue
                writer.writerow(
                    {
                        "character": item["character"],
                        "repeats": item["repeats"],
                        "purpose": item["purpose"],
                        "layout": item["layout"],
                        "components": " ".join(item["components"]),
                        "reason": "；".join(item["reasons"]),
                    }
                )
        incremental_paths.append(str(tier_path))

    result = {
        **value,
        "files": {
            "report": str(path),
            "master_csv": str(master_path),
            "incremental_collector_csvs": incremental_paths,
        },
    }
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


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
