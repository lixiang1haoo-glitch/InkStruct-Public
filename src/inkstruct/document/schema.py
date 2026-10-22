from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from uuid import uuid4

SCHEMA_VERSION = "inkstruct_document_v1"


def digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class SourceSpan:
    """Half-open Unicode scalar offsets into the unnormalized original source."""

    start: int
    end: int


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    span: SourceSpan
    severity: str = "error"


@dataclass(frozen=True)
class PageProfile:
    width_mm: float = 210.0
    height_mm: float = 297.0
    margin_mm: float = 20.0

    def __post_init__(self) -> None:
        if (
            not all(math.isfinite(v) for v in asdict(self).values())
            or self.margin_mm < 0
            or min(self.width_mm, self.height_mm) <= 2 * self.margin_mm
        ):
            raise ValueError("Page dimensions must be finite with a positive content area")


@dataclass(frozen=True)
class StyleProfile:
    em_mm: float = 6.0
    line_height_mm: float = 9.0
    stroke_width_mm: float = 0.3

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) and v > 0 for v in asdict(self).values()):
            raise ValueError("Style dimensions must be finite and positive")


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    node_id: str
    span: SourceSpan
    text: str


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    span: SourceSpan
    occurrences: tuple[Occurrence, ...]


@dataclass(frozen=True)
class Document:
    document_id: str
    revision: int
    source: str
    nodes: tuple[Node, ...]
    page: PageProfile
    style: StyleProfile
    schema_version: str = SCHEMA_VERSION
    source_mode: str = "plain-text"
    seed: int = 0

    @property
    def occurrences(self) -> tuple[Occurrence, ...]:
        return tuple(o for n in self.nodes for o in n.occurrences)


def new_id() -> str:
    return uuid4().hex
