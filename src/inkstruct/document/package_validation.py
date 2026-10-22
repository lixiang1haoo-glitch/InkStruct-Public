"""Strict package metadata decoding, independent of rendering and external resources."""

# ruff: noqa: TRY004 - invalid serialized values share the package ValueError boundary

import json
from dataclasses import asdict

from ..assets.resolver import SELECTION_VERSION
from ..editor.review import RATINGS, Review


def read_json(raw, expected, name):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key in {name}: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Non-finite JSON number in {name}: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON in {name}") from error
    if not isinstance(value, expected):
        raise ValueError(f"Invalid {name}: expected {expected.__name__}")
    return value


def validate_manifest(manifest):
    if type(manifest.get("seed")) is not int:
        raise ValueError("Invalid document selection seed")
    optimize = manifest.get("optimize")
    if type(optimize) is not bool:
        raise ValueError("Document optimize option must be boolean")
    reverse = manifest.get("allow_reverse", optimize)
    if type(reverse) is not bool or reverse != optimize:
        raise ValueError("Document path reversal must match optimization")
    if not isinstance(manifest.get("sha256"), dict):
        raise ValueError("Invalid document member hashes")


def validate_resources(records):
    if len(records) > 30_000:
        raise ValueError("Document exceeds 30,000 resource records")
    keys = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid glyph resource record")
        for key in (
            "asset_id",
            "character",
            "sample_id",
            "writer_id",
            "metrics_key",
            "provider_version",
            "source_file",
        ):
            if not isinstance(record.get(key), str) or not record[key]:
                raise ValueError(f"Invalid glyph resource {key}")
        key = (record["asset_id"], record["metrics_key"])
        if key in keys:
            raise ValueError("Duplicate glyph resource descriptor")
        keys.add(key)


def validate_selections(records):
    if len(records) > 100_000:
        raise ValueError("Document exceeds 100,000 selection records")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid selected asset record")
        for key in ("occurrence_id", "character", "asset_id", "sample_id", "metrics_key"):
            if not isinstance(record.get(key), str) or not record[key]:
                raise ValueError(f"Invalid selected asset {key}")
        if (type(record.get("warning_accepted", False)) is not bool or
            record.get("requested_style", "") not in {"", "upright", "italic"} or
            record.get("resolved_style", "") not in {"", "upright", "italic", "unspecified", "not_applicable"}):
            raise ValueError("Invalid font selection style or acknowledgement")
        if (
            len(record["character"]) != 1
            or record.get("selection_version", SELECTION_VERSION) != SELECTION_VERSION
        ):
            raise ValueError("Incompatible selected asset identity")


def validate_reviews(records):
    if not isinstance(records, (list, tuple)) or len(records) > 100_000:
        raise ValueError("Invalid document review list")
    result, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid document review record")
        try:
            review = Review(**record)
        except TypeError as error:
            raise ValueError("Invalid document review fields") from error
        fields = asdict(review)
        if (
            any(not isinstance(v, str) for k, v in fields.items() if k != "source_start")
            or len(review.asset_id) != 64
            or any(c not in "0123456789abcdef" for c in review.asset_id)
            or review.rating not in RATINGS
            or len(review.character) != 1
            or type(review.source_start) is not int
            or review.source_start < 0
        ):
            raise ValueError("Invalid document review values")
        if review.asset_id in seen:
            raise ValueError("Duplicate document glyph review")
        seen.add(review.asset_id)
        result.append(fields)
    return tuple(result)
