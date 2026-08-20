from datetime import UTC, datetime

from inkstruct.component_style import (
    component_context_key,
    component_relation_key,
    component_stroke_key,
    component_trajectory_key,
)
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import bbox, signature_key
from inkstruct.schemas import (
    ComponentLayoutPrototype,
    ComponentRelationPrototype,
    ComponentStrokePrototype,
    ComponentTrajectoryPrototype,
    StyleProfile,
)
from inkstruct.structures import graph_from_records


def make_graph(character: str, right: str):
    medians = [
        [[120, 780], [180, 700]],
        [[140, 600], [200, 530]],
        [[120, 400], [210, 300]],
        [[420, 760], [800, 760]],
        [[600, 820], [600, 240]],
        [[430, 300], [790, 300]],
    ]
    return graph_from_records(
        {"character": character, "medians": medians},
        {
            "character": character,
            "decomposition": f"⿰氵{right}",
            "radical": "氵",
            "matches": [[0], [0], [0], [1], [1], [1]],
        },
        simplified_characters={character},
        source_version="fixture",
    )


def test_component_conditioned_stroke_transfers_across_characters():
    graph = make_graph("池", "也")
    component = next(value for value in graph.components if value.path == "root.0")
    stroke = graph.strokes[0]
    signature = signature_key(stroke.signature)
    context_key = component_context_key(graph, component)
    stroke_key = component_stroke_key(graph, component, stroke.stroke_id, signature)
    profile = StyleProfile(
        schema_version="style_profile_v2",
        profile_version="fixture-components",
        writer_id="writer-1",
        created_at=datetime.now(UTC).isoformat(),
        source_index_sha256="fixture",
        sample_count=1,
        character_count=1,
        global_style={},
        prototypes={},
        coverage={},
        component_layouts={
            context_key: ComponentLayoutPrototype(
                key=context_key,
                canonical="水",
                glyph_variant="氵",
                role="left",
                parent_layout="⿰",
                bbox_delta=(0.03, 0.0, 0.03, 0.0),
                confidence=0.9,
                sample_count=1,
                source_character_count=1,
            )
        },
        component_strokes={
            stroke_key: ComponentStrokePrototype(
                key=stroke_key,
                canonical="水",
                glyph_variant="氵",
                role="left",
                parent_layout="⿰",
                component_stroke_index=1,
                component_stroke_count=3,
                signature=signature,
                residual=[(0.08, 0.0)] * 8,
                pressure=[0.6] * 8,
                duration_ms=120.0,
                confidence=0.9,
                sample_count=1,
                source_character_count=1,
                stroke_bbox_delta=(0.0, 0.0, 0.20, 0.0),
                start_delta=(-0.02, 0.0),
                end_delta=(0.02, 0.0),
            )
        },
    )
    component_glyph = DeterministicGenerator(profile, "fixture", "full").generate(graph)
    legacy_glyph = DeterministicGenerator(profile, "fixture", False).generate(graph)
    assert component_glyph.generator == "deterministic_component_residual_v2"
    assert component_glyph.strokes[0].style_source.startswith("component_exact+layout_exact")
    assert "component_geometry_exact" in component_glyph.strokes[0].style_source
    assert component_glyph.strokes[0].component_key == context_key
    component_points = [(point.x, point.y) for point in component_glyph.strokes[0].points]
    legacy_points = [(point.x, point.y) for point in legacy_glyph.strokes[0].points]
    assert component_points != legacy_points
    component_width = bbox(component_points)[2] - bbox(component_points)[0]
    legacy_width = bbox(legacy_points)[2] - bbox(legacy_points)[0]
    assert component_width > legacy_width


def test_joint_layout_relation_transfers_writer_balance():
    graph = make_graph("池", "也")
    component = next(value for value in graph.components if value.path == "root.0")
    relation_key = component_relation_key(graph, component)
    assert relation_key is not None
    profile = StyleProfile(
        schema_version="style_profile_v3",
        profile_version="fixture-relations",
        writer_id="writer-1",
        created_at=datetime.now(UTC).isoformat(),
        source_index_sha256="fixture",
        sample_count=8,
        character_count=8,
        global_style={},
        prototypes={},
        coverage={},
        component_relations={
            relation_key: ComponentRelationPrototype(
                key=relation_key,
                parent_layout="⿰",
                roles=["left", "right"],
                bbox_deltas={
                    "left": (0.0, -0.05, 0.08, 0.05),
                    "right": (0.0, 0.0, 0.0, 0.0),
                },
                confidence=0.9,
                sample_count=8,
                source_character_count=8,
            )
        },
    )
    related = DeterministicGenerator(profile, "fixture", "full").generate(graph)
    baseline = DeterministicGenerator(profile, "fixture", "off").generate(graph)
    related_points = [(point.x, point.y) for point in related.strokes[0].points]
    baseline_points = [(point.x, point.y) for point in baseline.strokes[0].points]
    assert bbox(related_points) != bbox(baseline_points)
    assert "layout_relation" in related.strokes[0].style_source


def test_whole_component_trajectory_places_all_strokes_in_one_frame():
    graph = make_graph("池", "也")
    component = next(value for value in graph.components if value.path == "root.0")
    trajectory_key = component_trajectory_key(graph, component)
    direct_key = f"池::{trajectory_key}"
    component_controls = [
        [(0.05 + index * 0.02, 0.10 + index * 0.04) for index in range(8)],
        [(0.15 + index * 0.02, 0.45 + index * 0.03) for index in range(8)],
        [(0.25 + index * 0.02, 0.75 + index * 0.02) for index in range(8)],
    ]
    trajectory = ComponentTrajectoryPrototype(
        key=direct_key,
        canonical=component.canonical,
        glyph_variant=component.glyph_variant,
        role=component.role,
        parent_layout="⿰",
        stroke_count=3,
        stroke_controls=component_controls,
        stroke_pressures=[[0.55] * 8, [0.60] * 8, [0.65] * 8],
        stroke_durations_ms=[100.0, 120.0, 140.0],
        confidence=0.9,
        sample_count=1,
        source_character_count=1,
    )
    profile = StyleProfile(
        schema_version="style_profile_v4",
        profile_version="fixture-whole-component",
        writer_id="writer-1",
        created_at=datetime.now(UTC).isoformat(),
        source_index_sha256="fixture",
        sample_count=1,
        character_count=1,
        global_style={},
        prototypes={},
        coverage={},
        character_component_trajectories={direct_key: trajectory},
    )
    whole = DeterministicGenerator(profile, "fixture", "adaptive").generate(graph)
    baseline = DeterministicGenerator(profile, "fixture", "off").generate(graph)
    assert whole.generator == "deterministic_component_trajectory_v4"
    assert all(stroke.style_source == "component_trajectory_direct" for stroke in whole.strokes[:3])
    assert [stroke.component_key for stroke in whole.strokes[:3]] == [
        component_context_key(graph, component)
    ] * 3
    assert [stroke.points[0].pressure for stroke in whole.strokes[:3]] == [
        0.55,
        0.60,
        0.65,
    ]
    assert [[(point.x, point.y) for point in stroke.points] for stroke in whole.strokes[:3]] != [
        [(point.x, point.y) for point in stroke.points] for stroke in baseline.strokes[:3]
    ]
