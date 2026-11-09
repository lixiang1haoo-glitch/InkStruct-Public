from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Point2D = tuple[float, float]


@dataclass(slots=True)
class StrokeSignature:
    directions: str
    turns: int
    curvature: float
    aspect: str
    hook: bool


@dataclass(slots=True)
class StandardStroke:
    stroke_id: str
    order: int
    median: list[Point2D]
    bbox: tuple[float, float, float, float]
    component_path: str
    signature: StrokeSignature
    stroke_type: str | None = None


@dataclass(slots=True)
class StrokeRelation:
    source: str
    target: str
    relation: Literal["precedes", "intersects", "touches", "left_of", "right_of", "above", "below"]


@dataclass(slots=True)
class ComponentNode:
    component_id: str
    path: str
    canonical: str
    glyph_variant: str
    role: str
    parent_id: str | None
    children_ids: list[str]
    stroke_ids: list[str]
    bbox: tuple[float, float, float, float]
    layout: str | None
    confidence: float


@dataclass(slots=True)
class CharacterGraph:
    schema_version: str
    character: str
    codepoint: str
    locale: str
    decomposition: str
    radical: str | None
    components: list[ComponentNode]
    component_warnings: list[str]
    strokes: list[StandardStroke]
    relations: list[StrokeRelation]
    source: str
    source_version: str
    confidence: float


@dataclass(slots=True)
class RawPoint:
    x: float
    y: float
    pressure: float
    t_ms: int


@dataclass(slots=True)
class RawStroke:
    stroke_index: int
    points: list[RawPoint]


@dataclass(slots=True)
class RawSample:
    schema_version: str
    sample_id: str
    writer_id: str
    character: str
    codepoint: str
    canvas_width: float
    canvas_height: float
    strokes: list[RawStroke]
    source_path: str
    source_sha256: str
    capture: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrokeMapping:
    standard_orders: list[int]
    user_orders: list[int]
    mapping_type: Literal["one_to_one", "one_to_many", "many_to_one"]
    cost: float
    confidence: float


@dataclass(slots=True)
class AlignedGlyph:
    schema_version: str
    sample_id: str
    writer_id: str
    character: str
    mappings: list[StrokeMapping]
    normalized_strokes: list[list[Point2D]]
    pressure_strokes: list[list[float]]
    time_strokes: list[list[int]]
    confidence: float
    warnings: list[str] = field(default_factory=list)
    stroke_order_status: Literal["declared", "corrected", "ambiguous", "not_applicable"] = (
        "declared"
    )
    stroke_permutation: list[int] = field(default_factory=list)
    order_confidence: float = 1.0
    order_identity_improvement: float = 0.0
    order_alternative_margin: float = 0.0
    # Captured order, before the legacy 16-point matching representation.
    # Shares point indices with pressure_strokes/time_strokes.
    source_normalized_strokes: list[list[Point2D]] = field(default_factory=list)


@dataclass(slots=True)
class StrokePrototype:
    key: str
    signature: str
    component_path: str
    residual: list[Point2D]
    pressure: list[float]
    duration_ms: float
    confidence: float
    sample_count: int


@dataclass(slots=True)
class ComponentLayoutPrototype:
    key: str
    canonical: str
    glyph_variant: str
    role: str
    parent_layout: str
    bbox_delta: tuple[float, float, float, float]
    confidence: float
    sample_count: int
    source_character_count: int


@dataclass(slots=True)
class ComponentStrokePrototype:
    key: str
    canonical: str
    glyph_variant: str
    role: str
    parent_layout: str
    component_stroke_index: int
    component_stroke_count: int
    signature: str
    residual: list[Point2D]
    pressure: list[float]
    duration_ms: float
    confidence: float
    sample_count: int
    source_character_count: int
    stroke_bbox_delta: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    start_delta: Point2D = (0.0, 0.0)
    end_delta: Point2D = (0.0, 0.0)


@dataclass(slots=True)
class ComponentRelationPrototype:
    key: str
    parent_layout: str
    roles: list[str]
    bbox_deltas: dict[str, tuple[float, float, float, float]]
    confidence: float
    sample_count: int
    source_character_count: int


@dataclass(slots=True)
class ComponentTrajectoryPrototype:
    """A whole component trajectory expressed in component-local coordinates.

    All strokes share the same coordinate frame.  This preserves their relative
    placement and shape instead of reconstructing a component from unrelated
    per-stroke prototypes.
    """

    key: str
    canonical: str
    glyph_variant: str
    role: str
    parent_layout: str
    stroke_count: int
    stroke_controls: list[list[Point2D]]
    stroke_pressures: list[list[float]]
    stroke_durations_ms: list[float]
    confidence: float
    sample_count: int
    source_character_count: int


@dataclass(slots=True)
class FactorizedStyleProfile:
    model_version: str
    checkpoint_sha256: str
    writer_latent: list[float]
    writer_log_variance: list[float]
    observed_structure_keys: list[str]
    uncertainty_summary: dict[str, float]


@dataclass(slots=True)
class SourceTrajectoryStroke:
    standard_stroke_id: str
    user_order: int
    points: list[Point2D]
    pressure: list[float]
    t_ms: list[int]
    arc_parameters: list[float]
    confidence: float


@dataclass(slots=True)
class SourceTrajectorySample:
    sample_id: str
    character: str
    source_sha256: str
    stroke_order_status: str
    strokes: list[SourceTrajectoryStroke]


@dataclass(slots=True)
class StyleProfile:
    schema_version: str
    profile_version: str
    writer_id: str
    created_at: str
    source_index_sha256: str
    sample_count: int
    character_count: int
    global_style: dict[str, float]
    prototypes: dict[str, StrokePrototype]
    coverage: dict[str, Any]
    component_layouts: dict[str, ComponentLayoutPrototype] = field(default_factory=dict)
    character_layouts: dict[str, ComponentLayoutPrototype] = field(default_factory=dict)
    component_strokes: dict[str, ComponentStrokePrototype] = field(default_factory=dict)
    component_relations: dict[str, ComponentRelationPrototype] = field(default_factory=dict)
    component_trajectories: dict[str, ComponentTrajectoryPrototype] = field(default_factory=dict)
    character_component_trajectories: dict[str, ComponentTrajectoryPrototype] = field(
        default_factory=dict
    )
    excluded_samples: list[dict[str, str]] = field(default_factory=list)
    style_tokens: list[list[float]] = field(default_factory=list)
    factorized_style: FactorizedStyleProfile | None = None
    trajectory_schema: str | None = None
    source_trajectories: dict[str, SourceTrajectorySample] = field(default_factory=dict)
    build_identity: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GeneratedPoint:
    x: float
    y: float
    t_ms: int
    pressure: float
    pen_state: Literal["down", "up", "end"]


@dataclass(slots=True)
class GeneratedStroke:
    standard_stroke_id: str
    order: int
    confidence: float
    points: list[GeneratedPoint]
    style_source: str = "global"
    component_key: str | None = None


@dataclass(slots=True)
class GeneratedGlyph:
    schema_version: str
    character: str
    codepoint: str
    locale: str
    writer_id: str
    structure_version: str
    profile_version: str
    generator: str
    confidence: float
    strokes: list[GeneratedStroke]
    canvas_fit: dict[str, Any] = field(default_factory=dict)


def to_dict(value: Any) -> Any:
    """Recursively convert schema dataclasses to JSON-safe dictionaries."""
    return asdict(value)
