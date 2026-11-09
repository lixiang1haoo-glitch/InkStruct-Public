from __future__ import annotations

import csv
import hashlib
import json
import math
import pickle
import sqlite3
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from .geometry import bbox, stroke_signature
from .schemas import (
    CharacterGraph,
    ComponentNode,
    StandardStroke,
    StrokeRelation,
    StrokeSignature,
)

SCHEMA_VERSION = "character_graph_v2"
DEFAULT_DATABASE = Path("artifacts/structures/characters.sqlite3")
MAINLAND_SIMPLIFIED_PACKAGE = "mainland_standard_simplified_gb2312"
NON_MAINLAND_SIMPLIFIED_PACKAGE = "non_mainland_standard_simplified"
CHARACTER_PACKAGES = (MAINLAND_SIMPLIFIED_PACKAGE, NON_MAINLAND_SIMPLIFIED_PACKAGE)

IDS_ARITY = {
    "⿰": 2,
    "⿱": 2,
    "⿲": 3,
    "⿳": 3,
    "⿴": 2,
    "⿵": 2,
    "⿶": 2,
    "⿷": 2,
    "⿸": 2,
    "⿹": 2,
    "⿺": 2,
    "⿻": 2,
}

COMPONENT_VARIANTS = {
    "亻": "人",
    "刂": "刀",
    "忄": "心",
    "⺗": "心",
    "扌": "手",
    "氵": "水",
    "灬": "火",
    "爫": "爪",
    "犭": "犬",
    "礻": "示",
    "糹": "糸",
    "纟": "糸",
    "衤": "衣",
    "訁": "言",
    "讠": "言",
    "釒": "金",
    "钅": "金",
    "飠": "食",
    "饣": "食",
    "阝": "阜/邑",
}

ROLE_BY_LAYOUT = {
    "⿰": ("left", "right"),
    "⿱": ("top", "bottom"),
    "⿲": ("left", "middle", "right"),
    "⿳": ("top", "middle", "bottom"),
    "⿴": ("surround", "inside"),
    "⿵": ("surround-top", "inside"),
    "⿶": ("surround-bottom", "inside"),
    "⿷": ("surround-left", "inside"),
    "⿸": ("surround-top-left", "inside"),
    "⿹": ("surround-top-right", "inside"),
    "⿺": ("surround-bottom-left", "inside"),
    "⿻": ("overlap-primary", "overlap-secondary"),
}


@dataclass(slots=True)
class _IdsNode:
    value: str
    path: tuple[int, ...]
    children: list[_IdsNode]


def _parse_ids(decomposition: str) -> _IdsNode:
    position = 0

    def parse(path: tuple[int, ...]) -> _IdsNode:
        nonlocal position
        if position >= len(decomposition):
            raise ValueError("IDS ended before all children were parsed")
        value = decomposition[position]
        position += 1
        children = [parse((*path, index)) for index in range(IDS_ARITY.get(value, 0))]
        return _IdsNode(value, path, children)

    root = parse(())
    if position != len(decomposition):
        raise ValueError("IDS contains trailing tokens")
    return root


def _ids_text(node: _IdsNode) -> str:
    return node.value + "".join(_ids_text(child) for child in node.children)


def _component_id(path: tuple[int, ...]) -> str:
    return "c_root" if not path else "c_" + "_".join(str(value) for value in path)


def _component_path_from_tuple(path: tuple[int, ...]) -> str:
    return "root" + "".join(f".{value}" for value in path)


def _component_bbox(stroke_ids: list[str], strokes: list[StandardStroke]):
    selected = [stroke.bbox for stroke in strokes if stroke.stroke_id in stroke_ids]
    if not selected:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(value[0] for value in selected),
        min(value[1] for value in selected),
        max(value[2] for value in selected),
        max(value[3] for value in selected),
    )


def _component_nodes(
    character: str,
    decomposition: str,
    matches: list | None,
    strokes: list[StandardStroke],
) -> tuple[list[ComponentNode], list[str]]:
    root_bbox = _component_bbox([stroke.stroke_id for stroke in strokes], strokes)
    warnings: list[str] = []
    if not decomposition or decomposition == "？" or "？" in decomposition:
        warnings.append("IDS decomposition is missing or contains an unknown component")
    try:
        ids_root = _parse_ids(decomposition)
    except ValueError as error:
        ids_root = _IdsNode("？", (), [])
        warnings.append(str(error))

    normalized_matches: list[tuple[int, ...] | None] = []
    for index in range(len(strokes)):
        raw = matches[index] if isinstance(matches, list) and index < len(matches) else None
        try:
            normalized_matches.append(
                tuple(int(value) for value in raw) if isinstance(raw, list) else None
            )
        except (TypeError, ValueError):
            normalized_matches.append(None)
    if ids_root.children and any(value is None for value in normalized_matches):
        warnings.append("one or more strokes have no component match")

    nodes: list[ComponentNode] = [
        ComponentNode(
            component_id="c_root",
            path="root",
            canonical=character,
            glyph_variant=character,
            role="root",
            parent_id=None,
            children_ids=[_component_id(child.path) for child in ids_root.children],
            stroke_ids=[stroke.stroke_id for stroke in strokes],
            bbox=root_bbox,
            layout=ids_root.value if ids_root.value in IDS_ARITY else None,
            confidence=1.0 if not warnings else 0.7,
        )
    ]

    def visit(node: _IdsNode, parent: _IdsNode) -> None:
        prefix = node.path
        stroke_ids = [
            stroke.stroke_id
            for stroke, match in zip(strokes, normalized_matches)
            if match is not None and match[: len(prefix)] == prefix
        ]
        roles = ROLE_BY_LAYOUT.get(parent.value, ())
        child_index = node.path[-1]
        role = roles[child_index] if child_index < len(roles) else f"child-{child_index}"
        variant = _ids_text(node)
        canonical = COMPONENT_VARIANTS.get(node.value, node.value) if not node.children else variant
        confidence = 1.0
        if "？" in variant:
            confidence = 0.4
        if not stroke_ids:
            confidence = min(confidence, 0.25)
            warnings.append(f"component {_component_path_from_tuple(node.path)} has no strokes")
        nodes.append(
            ComponentNode(
                component_id=_component_id(node.path),
                path=_component_path_from_tuple(node.path),
                canonical=canonical,
                glyph_variant=variant,
                role=role,
                parent_id=_component_id(node.path[:-1]),
                children_ids=[_component_id(child.path) for child in node.children],
                stroke_ids=stroke_ids,
                bbox=_component_bbox(stroke_ids, strokes),
                layout=node.value if node.value in IDS_ARITY else None,
                confidence=confidence,
            )
        )
        for child in node.children:
            visit(child, node)

    for child in ids_root.children:
        visit(child, ids_root)
    return nodes, list(dict.fromkeys(warnings))


def _read_json_lines(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error


def _load_dictionary(path: Path) -> dict[str, dict]:
    return {
        record["character"]: record
        for record in _read_json_lines(path)
        if isinstance(record.get("character"), str) and len(record["character"]) == 1
    }


def _load_simplified_characters(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    if path.suffix.lower() in {".pkl", ".pickle"}:
        with path.open("rb") as stream:
            value = pickle.load(stream)
        if isinstance(value, dict):
            return {str(key) for key in value if len(str(key)) == 1}
        return {str(item) for item in value if len(str(item)) == 1}
    return {character for character in path.read_text(encoding="utf-8") if not character.isspace()}


def _normalise_median(raw_points: list[list[float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for value in raw_points:
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("median point is not a coordinate pair")
        x, source_y = float(value[0]), float(value[1])
        if not math.isfinite(x) or not math.isfinite(source_y):
            raise ValueError("median contains a non-finite coordinate")
        # Make Me a Hanzi uses a 1024 em coordinate space with Y pointing up.
        result.append((min(1.0, max(0.0, x / 1024.0)), min(1.0, max(0.0, 1 - source_y / 1024.0))))
    if len(result) < 2:
        raise ValueError("median has fewer than two points")
    return result


def _component_path(matches: list | None, stroke_index: int) -> str:
    if not matches or stroke_index >= len(matches) or matches[stroke_index] is None:
        return "root"
    path = matches[stroke_index]
    if not isinstance(path, list):
        return "root"
    return "root" + "".join(f".{int(index)}" for index in path)


def _bbox_gap(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> tuple[float, float]:
    x_gap = max(0.0, max(left[0], right[0]) - min(left[2], right[2]))
    y_gap = max(0.0, max(left[1], right[1]) - min(left[3], right[3]))
    return x_gap, y_gap


def _relations(strokes: list[StandardStroke]) -> list[StrokeRelation]:
    relations: list[StrokeRelation] = []
    for left, right in pairwise(strokes):
        relations.append(StrokeRelation(left.stroke_id, right.stroke_id, "precedes"))
    for index, left in enumerate(strokes):
        lx0, ly0, lx1, ly1 = left.bbox
        lcx, lcy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
        for right in strokes[index + 1 :]:
            rx0, ry0, rx1, ry1 = right.bbox
            rcx, rcy = (rx0 + rx1) / 2, (ry0 + ry1) / 2
            x_gap, y_gap = _bbox_gap(left.bbox, right.bbox)
            overlap_x = min(lx1, rx1) >= max(lx0, rx0)
            overlap_y = min(ly1, ry1) >= max(ly0, ry0)
            if overlap_x and overlap_y:
                relation = "intersects"
            elif math.hypot(x_gap, y_gap) <= 0.025:
                relation = "touches"
            elif abs(lcx - rcx) > abs(lcy - rcy):
                relation = "left_of" if lcx < rcx else "right_of"
            else:
                relation = "above" if lcy < rcy else "below"
            relations.append(StrokeRelation(left.stroke_id, right.stroke_id, relation))
    return relations


def graph_from_records(
    graphics: dict,
    dictionary: dict | None,
    *,
    simplified_characters: set[str],
    source_version: str,
) -> CharacterGraph:
    character = graphics.get("character")
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError("record does not contain one character")
    medians = graphics.get("medians")
    if not isinstance(medians, list) or not medians:
        raise ValueError("character has no medians")
    dictionary = dictionary or {}
    matches = dictionary.get("matches")
    strokes: list[StandardStroke] = []
    for index, raw_median in enumerate(medians):
        median = _normalise_median(raw_median)
        strokes.append(
            StandardStroke(
                stroke_id=f"s{index + 1}",
                order=index + 1,
                median=median,
                bbox=bbox(median),
                component_path=_component_path(matches, index),
                signature=stroke_signature(median),
            )
        )
    locale = "zh-Hans" if character in simplified_characters else "zh-Hant-generic"
    decomposition = str(dictionary.get("decomposition") or "？")
    components, component_warnings = _component_nodes(character, decomposition, matches, strokes)
    return CharacterGraph(
        schema_version=SCHEMA_VERSION,
        character=character,
        codepoint=f"U+{ord(character):04X}",
        locale=locale,
        decomposition=decomposition,
        radical=dictionary.get("radical"),
        components=components,
        component_warnings=component_warnings,
        strokes=strokes,
        relations=_relations(strokes),
        source="Make Me a Hanzi",
        source_version=source_version,
        confidence=1.0 if dictionary else 0.85,
    )


def _json_default(value):
    if isinstance(value, StrokeSignature):
        return asdict(value)
    raise TypeError(type(value).__name__)


def build_database(
    graphics_path: Path,
    dictionary_path: Path,
    database_path: Path = DEFAULT_DATABASE,
    *,
    simplified_path: Path | None = None,
    source_version: str = "unknown",
) -> dict:
    graphics_path = graphics_path.resolve()
    dictionary_path = dictionary_path.resolve()
    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    dictionary = _load_dictionary(dictionary_path)
    simplified = _load_simplified_characters(simplified_path)
    rejected: list[dict[str, str]] = []
    accepted = 0
    complete_components = 0
    fallback_components: list[dict[str, object]] = []
    temporary = database_path.with_suffix(database_path.suffix + ".building")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE characters (
                character TEXT PRIMARY KEY,
                codepoint TEXT NOT NULL UNIQUE,
                locale TEXT NOT NULL,
                stroke_count INTEGER NOT NULL,
                decomposition TEXT NOT NULL,
                graph_json TEXT NOT NULL
            );
            CREATE INDEX idx_characters_locale ON characters(locale);
            CREATE INDEX idx_characters_strokes ON characters(stroke_count);
            """
        )
        for record in _read_json_lines(graphics_path):
            character = str(record.get("character", ""))
            try:
                graph = graph_from_records(
                    record,
                    dictionary.get(character),
                    simplified_characters=simplified,
                    source_version=source_version,
                )
                payload = json.dumps(
                    asdict(graph), ensure_ascii=False, separators=(",", ":"), default=_json_default
                )
                connection.execute(
                    "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        graph.character,
                        graph.codepoint,
                        graph.locale,
                        len(graph.strokes),
                        graph.decomposition,
                        payload,
                    ),
                )
                accepted += 1
                if graph.component_warnings:
                    fallback_components.append(
                        {
                            "character": graph.character,
                            "warnings": graph.component_warnings,
                        }
                    )
                else:
                    complete_components += 1
            except (TypeError, ValueError, sqlite3.IntegrityError) as error:
                rejected.append({"character": character, "reason": str(error)})
        created_at = datetime.now(UTC).isoformat()
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "created_at": created_at,
            "source": "Make Me a Hanzi",
            "source_version": source_version,
            "graphics_path": str(graphics_path),
            "dictionary_path": str(dictionary_path),
            "accepted_count": str(accepted),
            "rejected_count": str(len(rejected)),
            "coordinate_space": "normalized_em_y_down",
            "component_schema": "component_tree_v1",
            "component_complete_count": str(complete_components),
            "component_fallback_count": str(len(fallback_components)),
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        connection.commit()
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    temporary.replace(database_path)
    report = {
        "schema_version": "structure_build_report_v2",
        "database": str(database_path),
        "accepted_count": accepted,
        "rejected_count": len(rejected),
        "rejected": rejected,
        "component_complete_count": complete_components,
        "component_fallback_count": len(fallback_components),
        "component_fallback_report": str(database_path.with_name("component_fallback_report.json")),
        "sources": [
            {"name": "Make Me a Hanzi dictionary", "license": "LGPL-3.0-or-later"},
            {"name": "Make Me a Hanzi graphics", "license": "Arphic Public License"},
        ],
    }
    fallback_report_path = database_path.with_name("component_fallback_report.json")
    fallback_report_path.write_text(
        json.dumps(
            {
                "schema_version": "component_fallback_report_v1",
                "count": len(fallback_components),
                "characters": fallback_components,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = database_path.with_name("build_report.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _signature_from_dict(value: dict) -> StrokeSignature:
    return StrokeSignature(**value)


def graph_from_dict(value: dict) -> CharacterGraph:
    strokes = []
    for item in value["strokes"]:
        item = dict(item)
        item["median"] = [tuple(point) for point in item["median"]]
        item["bbox"] = tuple(item["bbox"])
        item["signature"] = _signature_from_dict(item["signature"])
        strokes.append(StandardStroke(**item))
    relations = [StrokeRelation(**item) for item in value["relations"]]
    components = [
        ComponentNode(**{**item, "bbox": tuple(item["bbox"])})
        for item in value.get("components", [])
    ]
    if not components:
        components = [
            ComponentNode(
                component_id="c_root",
                path="root",
                canonical=value["character"],
                glyph_variant=value["character"],
                role="root",
                parent_id=None,
                children_ids=[],
                stroke_ids=[stroke.stroke_id for stroke in strokes],
                bbox=_component_bbox([stroke.stroke_id for stroke in strokes], strokes),
                layout=None,
                confidence=0.5,
            )
        ]
    return CharacterGraph(
        **{
            **value,
            "components": components,
            "component_warnings": value.get(
                "component_warnings", ["legacy graph has no component tree"]
            ),
            "strokes": strokes,
            "relations": relations,
        }
    )


class StructureRepository:
    def __init__(self, database_path: Path = DEFAULT_DATABASE):
        self.path = Path(database_path)
        if not self.path.is_file():
            raise FileNotFoundError(f"structure database not found: {self.path}")

    def get(self, character: str) -> CharacterGraph:
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT graph_json FROM characters WHERE character = ?", (character,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(f"unsupported character: {character}")
        return graph_from_dict(json.loads(row[0]))

    def characters(self) -> list[str]:
        connection = sqlite3.connect(self.path)
        try:
            rows = connection.execute(
                "SELECT character FROM characters ORDER BY codepoint"
            ).fetchall()
        finally:
            connection.close()
        return [row[0] for row in rows]

    def iter_graphs(self) -> Iterator[CharacterGraph]:
        connection = sqlite3.connect(self.path)
        try:
            cursor = connection.execute("SELECT graph_json FROM characters ORDER BY codepoint")
            for row in cursor:
                yield graph_from_dict(json.loads(row[0]))
        finally:
            connection.close()

    def count(self) -> int:
        connection = sqlite3.connect(self.path)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM characters").fetchone()[0])
        finally:
            connection.close()

    def metadata(self) -> dict[str, str]:
        connection = sqlite3.connect(self.path)
        try:
            return dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()

    def content_sha256(self) -> str:
        """Hash logical structure content, including committed WAL changes.

        Exclude machine-specific paths and build timestamps. Read metadata and
        graphs in one SQLite snapshot instead of hashing only the main DB file.
        """
        digest = hashlib.sha256()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("BEGIN")
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            identity = {key: metadata.get(key) for key in (
                "schema_version", "source", "source_version", "coordinate_space", "component_schema"
            )}
            digest.update(json.dumps(identity, sort_keys=True).encode())
            for character, payload in connection.execute(
                "SELECT character, graph_json FROM characters ORDER BY codepoint"
            ):
                digest.update(json.dumps(
                    [character, json.loads(payload)], sort_keys=True, separators=(",", ":")
                ).encode())
                digest.update(b"\n")
        finally:
            connection.close()
        return digest.hexdigest()


def _is_gb2312_hanzi(character: str) -> bool:
    if len(character) != 1 or not "\u3400" <= character <= "\u9fff":
        return False
    try:
        encoded = character.encode("gb2312")
    except UnicodeEncodeError:
        return False
    return len(encoded) == 2


def character_package(character: str) -> str:
    return (
        MAINLAND_SIMPLIFIED_PACKAGE
        if _is_gb2312_hanzi(character)
        else NON_MAINLAND_SIMPLIFIED_PACKAGE
    )


def package_characters(
    structures: StructureRepository, package: str
) -> list[str]:
    if package not in CHARACTER_PACKAGES:
        raise ValueError(f"unknown character package: {package}")
    return [
        graph.character
        for graph in structures.iter_graphs()
        if character_package(graph.character) == package
    ]


def export_character_packages(
    structures: StructureRepository, output_dir: Path
) -> dict[str, object]:
    """Export a complete, disjoint GB2312/non-GB2312 partition of the structure library."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = {package: [] for package in CHARACTER_PACKAGES}
    locale_mismatches = []
    for graph in structures.iter_graphs():
        package = character_package(graph.character)
        expected_locale = "zh-Hans" if package == MAINLAND_SIMPLIFIED_PACKAGE else "zh-Hant-generic"
        if graph.locale != expected_locale:
            locale_mismatches.append(
                {
                    "character": graph.character,
                    "locale": graph.locale,
                    "expected_locale": expected_locale,
                }
            )
        rows[package].append(
            {
                "character": graph.character,
                "codepoint": graph.codepoint,
                "package": package,
                "locale": graph.locale,
                "stroke_count": len(graph.strokes),
                "component_status": (
                    "fallback" if graph.component_warnings else "complete"
                ),
                "decomposition": graph.decomposition,
            }
        )
    if locale_mismatches:
        raise RuntimeError(
            f"GB2312 package disagrees with structure locale for {len(locale_mismatches)} characters"
        )

    fieldnames = [
        "character",
        "codepoint",
        "package",
        "locale",
        "stroke_count",
        "component_status",
        "decomposition",
    ]
    files = {}
    hashes = {}
    for package, package_rows in rows.items():
        path = output_dir / f"{package}_characters.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(package_rows)
        files[package] = str(path)
        hashes[package] = hashlib.sha256(
            "".join(row["character"] for row in package_rows).encode("utf-8")
        ).hexdigest()

    return {
        "schema_version": "character_package_partition_v1",
        "definition": {
            MAINLAND_SIMPLIFIED_PACKAGE: (
                "All Han characters in the structure library encodable as GB2312; "
                "exactly matches locale=zh-Hans in this database."
            ),
            NON_MAINLAND_SIMPLIFIED_PACKAGE: (
                "All remaining supported characters, including traditional forms, "
                "variants and radicals."
            ),
        },
        "database_character_count": structures.count(),
        "counts": {package: len(package_rows) for package, package_rows in rows.items()},
        "character_sha256": hashes,
        "locale_mismatch_count": 0,
        "files": files,
    }
