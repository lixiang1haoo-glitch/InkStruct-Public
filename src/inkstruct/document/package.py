"""Minimal .inkdoc package: authoritative source, identities, choices and embedded assets."""

from __future__ import annotations

import base64
import io
import json
import math
import zipfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from ..assets.glyph_provider import GlyphMetrics
from ..assets.resolver import AssetResolver, SelectedAsset
from ..assets.symbol_provider import ResolvedGlyph
from ..editor.review import atomic_write
from ..fonts.identity import KEYS as FONT_RELEASE_KEYS
from ..fonts.identity import embedded_identity, release_identity
from ..math.schema import MATH_VERSION
from .editing import SourceSession
from .han_variation import variation_record
from .markdown import dialect_version
from .package_validation import (
    read_json,
    validate_manifest,
    validate_resources,
    validate_reviews,
    validate_selections,
)
from .schema import PageProfile, StyleProfile
from .styles import FlowStyle
from .template_revision import template_record

VERSION = "inkstruct_document_package_v1"
FONT_VERSION = "inkstruct_document_package_v2"
TEMPLATE_VERSION = "inkstruct_document_package_v3"
# Only these exact historical grammars are accepted, never arbitrary revisions.
PACKAGE_DIALECTS = {
    name: frozenset({
        dialect_version(name),
        dialect_version(name).removesuffix("/break-commands-v2"),
        dialect_version(name).removesuffix("/break-commands-v2") + "/break-commands-v1",
    })
    for name in ("markdown", "obsidian")
}
MAX_MEMBER_BYTES = 16_000_000
# Catalogs aggregate many individually bounded glyphs, including font provenance.
# The writer can legitimately exceed the per-glyph/member size in this one index.
MAX_RESOURCE_CATALOG_BYTES = 128_000_000


@dataclass
class LoadedDocument:
    session: SourceSession
    resolver: AssetResolver
    page: PageProfile
    style: StyleProfile
    optimize: bool
    file_hash: str
    flow: FlowStyle
    reviews: tuple[dict, ...] = ()
    migration_notice: str = ""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def package_bytes(
    session: SourceSession,
    resolver: AssetResolver,
    page: PageProfile,
    style: StyleProfile,
    *,
    optimize=False,
    flow=None,
    reviews=(),
) -> bytes:
    reviews = validate_reviews(reviews)
    if type(resolver.seed) is not int:
        raise ValueError("Invalid document selection seed")
    if type(optimize) is not bool:
        raise ValueError("Document optimize option must be boolean")
    available = {
        (g.asset_id, g.sample_id, g.metrics_key, g.character)
        for pool in resolver.pools.values()
        for g in pool
    }
    if any(
        (s.asset_id, s.sample_id, s.metrics_key, s.character) not in available
        for s in resolver.selections.values()
    ):
        raise ValueError("Cannot save while a selected resource is unavailable")
    members = {}
    from ..math.style import math_style_record

    flow_record = asdict(flow or FlowStyle())
    if flow and flow.template:
        flow_record['template'] = template_record(flow.template, flow_record['template'])
    flow_record["han_variation"] = variation_record((flow or FlowStyle()).han_variation)
    flow_record["math"] = math_style_record((flow or FlowStyle()).math)
    for image_style in [flow_record["image"], *(v for _, v in flow_record["image_overrides"])]:
        if image_style["schema_version"] == "inkstruct_image_style_v1":
            image_style.pop("height_mm")
    if flow_record["schema_version"] not in {"inkstruct_flow_style_v3", "inkstruct_flow_style_v4", "inkstruct_flow_style_v5"}:
        flow_record.pop("latin_spacing")
    if flow_record["schema_version"] not in {"inkstruct_flow_style_v4", "inkstruct_flow_style_v5"}:
        flow_record.pop("punctuation_spacing")
    if flow_record["schema_version"] != "inkstruct_flow_style_v5":
        flow_record.pop("paragraph_align")
        flow_record.pop("han_variation")
    for record in flow_record["images"]:
        for prefix in (
            ("original",)
            if record.get("schema_version") == "inkstruct_line_svg_v1"
            else ("original", "png")
        ):
            filename = f"images/{record[prefix + '_sha256']}.{prefix}"
            members[filename] = base64.b64decode(record.pop(prefix + "_base64"), validate=True)
            record[prefix + "_file"] = filename
    members.update(
        {
            "source.md": session.source.encode("utf-8"),
            "identity.json": _json(session.identity_record()),
            "styles.json": _json(
                {"page": asdict(page), "body": asdict(style), "flow": flow_record}
            ),
            "reviews.json": _json(list(reviews)),
            "selections.json": _json(resolver.selection_records()),
        }
    )
    resources = []
    for char in sorted(resolver.pools):
        for glyph in resolver.pools[char]:
            record = asdict(glyph)
            raw = record.pop("original_json")
            raw_hash = sha256(raw).hexdigest()
            filename = f"assets/{raw_hash}.json"
            record["source_file"] = filename
            resources.append(record)
            members[filename] = raw
    members["resources.json"] = _json(resources)
    if resolver.font_identity:
        members['font-source.json'] = _json({
            'schema_version': 'inkstruct_font_source_v1',
            **dict(zip(FONT_RELEASE_KEYS, resolver.font_identity, strict=True)),
        })
    manifest = {
        "schema_version": TEMPLATE_VERSION if (flow or FlowStyle()).named_fields else FONT_VERSION if any(g.font_core for pool in resolver.pools.values() for g in pool) else VERSION,
        "dialect": dialect_version(flow_record["markdown_dialect"]),
        "math_version": MATH_VERSION,
        "seed": resolver.seed,
        "optimize": optimize,
        "allow_reverse": optimize,
        "sha256": {name: sha256(raw).hexdigest() for name, raw in members.items()},
    }
    if (flow or FlowStyle()).named_fields:
        manifest["template_content_protocol"] = "inkstruct_named_fields_v1"
    members["manifest.json"] = _json(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    return buffer.getvalue()


def _glyph(record, members):
    record = dict(record)
    filename = record.pop("source_file")
    raw = members[filename]
    if filename != f"assets/{sha256(raw).hexdigest()}.json":
        raise ValueError("Invalid embedded glyph resource reference")
    record["original_json"] = raw
    record["metrics"] = GlyphMetrics(**record["metrics"])
    strokes = tuple(tuple(tuple(p) for p in stroke) for stroke in record["strokes"])
    if not strokes or any(not s for s in strokes) or sum(map(len, strokes)) > (100_000 if record.get("provider_version") == "inkfont-core-v1" else 4096):
        raise ValueError("Invalid embedded stroke count")
    if any(
        len(p) != 2 or any(not math.isfinite(v) or abs(v) > 10 for v in p)
        for s in strokes
        for p in s
    ):
        raise ValueError("Invalid embedded coordinates")
    record["strokes"] = strokes
    glyph = ResolvedGlyph(**record)
    if len(glyph.character) != 1:
        raise ValueError("Invalid embedded character")
    if glyph.provider_version == "inkfont-core-v1":
        from ..fonts.core import from_embedded
        if glyph != from_embedded(raw):
            raise ValueError("Embedded font core differs from immutable trajectory")
    elif glyph.provider_version == "builtin-numeric-em-v1":
        from ..assets.builtin import numeric_assets

        if glyph != numeric_assets().get(glyph.character):
            raise ValueError("Builtin glyph descriptor mismatch")
    else:
        if sha256(raw).hexdigest() != glyph.asset_id:
            raise ValueError("Embedded source hash mismatch")
        original = read_json(raw, dict, filename)
        if original["character"] != glyph.character:
            raise ValueError("Embedded source character mismatch")
        if original["schema_version"] == "inkstruct_symbol_sample_v1":
            guide = original["guides"]
            expected = tuple(
                tuple(
                    (
                        (float(p["x"]) - float(guide["origin_x_px"])) / float(guide["em_px"]),
                        glyph.metrics.baseline
                        + (float(p["y"]) - float(guide["baseline_y_px"])) / float(guide["em_px"]),
                    )
                    for p in s["points"]
                )
                for s in original["strokes"]
            )
        elif original["schema_version"] == "personal_trajectory_v1":
            expected = tuple(
                tuple((p["x"], p["y"]) for p in s["points"]) for s in original["strokes"]
            )
        else:
            raise ValueError("Unsupported embedded source schema")
        if expected != glyph.strokes:
            raise ValueError("Embedded geometry differs from its immutable source")
    return glyph


def load_package(path: Path) -> LoadedDocument:
    path = Path(path)
    if path.stat().st_size > 200_000_000:
        raise ValueError("Project exceeds 200 MB")
    raw = path.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 30_000
                or sum(e.file_size for e in entries) > 500_000_000
                or any(e.file_size > (
                    MAX_RESOURCE_CATALOG_BYTES if e.filename == "resources.json" else MAX_MEMBER_BYTES
                ) for e in entries)
                or len({e.filename for e in entries}) != len(entries)
            ):
                raise ValueError("Invalid or oversized document package")
            try:
                members = {e.filename: archive.read(e) for e in entries}
            except (RuntimeError, NotImplementedError) as error:
                raise ValueError("Unsupported or encrypted project archive") from error
        manifest = read_json(members.pop("manifest.json"), dict, "manifest.json")
        validate_manifest(manifest)
        if manifest['schema_version']==TEMPLATE_VERSION and set(manifest)!={
                'schema_version','dialect','math_version','seed','optimize','allow_reverse','sha256','template_content_protocol'}:
            raise ValueError('Unknown template project manifest fields')
        if manifest["schema_version"] not in {VERSION, FONT_VERSION, TEMPLATE_VERSION} or manifest["dialect"] not in frozenset().union(*PACKAGE_DIALECTS.values()):
            raise ValueError("Unsupported document package or dialect version")
        if manifest.get("math_version", MATH_VERSION) != MATH_VERSION:
            raise ValueError("Unsupported math grammar version")
        if manifest["sha256"] != {k: sha256(v).hexdigest() for k, v in members.items()}:
            raise ValueError("Document package member hash mismatch")
        session = SourceSession.restore(
            members["source.md"].decode("utf-8"),
            read_json(members["identity.json"], dict, "identity.json"),
        )
        styles = read_json(members["styles.json"], dict, "styles.json")
        if (
            manifest["dialect"] not in PACKAGE_DIALECTS.get(
                styles.get("flow", {}).get("markdown_dialect", "markdown"), ()
            )
        ):
            raise ValueError("Document manifest and flow dialect disagree")
        for record in styles.get("flow", {}).get("images", []):
            for prefix in (
                ("original",)
                if record.get("schema_version") == "inkstruct_line_svg_v1"
                else ("original", "png")
            ):
                filename = record.pop(prefix + "_file")
                if filename != f"images/{record[prefix + '_sha256']}.{prefix}":
                    raise ValueError("Invalid embedded image resource reference")
                record[prefix + "_base64"] = base64.b64encode(members[filename]).decode("ascii")
        resources = read_json(members["resources.json"], list, "resources.json")
        choices = read_json(members["selections.json"], list, "selections.json")
        reviews = validate_reviews(
            read_json(members.get("reviews.json", b"[]"), list, "reviews.json")
        )
        validate_resources(resources)
        validate_selections(choices)
        glyphs = tuple(_glyph(r, members) for r in resources)
        selections = tuple(SelectedAsset(**s) for s in choices)
        if 'font-source.json' in members:
            font_record = read_json(members['font-source.json'], dict, 'font-source.json')
            identity = release_identity(font_record)
            if (set(font_record) != {'schema_version', *FONT_RELEASE_KEYS}
                    or font_record['schema_version'] != 'inkstruct_font_source_v1' or identity is None):
                raise ValueError("Invalid document font release reference")
        else:
            identity = embedded_identity(glyphs)
        resolver = AssetResolver(embedded=glyphs, seed=manifest["seed"], selections=selections,
                                 font_identity=identity)
        for selection in selections:
            if not any(
                (g.asset_id, g.sample_id, g.metrics_key)
                == (selection.asset_id, selection.sample_id, selection.metrics_key)
                for g in resolver.pools.get(selection.character, ())
            ):
                raise ValueError("Selected glyph is missing from the embedded resource set")
        flow_record = dict(styles.get("flow", {}))
        flow_record.setdefault("math", {"fraction_source": "geometric"})
        flow = FlowStyle(**flow_record)
        if flow.named_fields != (manifest["schema_version"] == TEMPLATE_VERSION):
            raise ValueError("Template and project protocol versions disagree")
        if flow.named_fields and (manifest.get("template_content_protocol") != "inkstruct_named_fields_v1"
                                  or styles['flow'].get('schema_version') not in {'inkstruct_flow_style_v2', 'inkstruct_flow_style_v3', 'inkstruct_flow_style_v4', 'inkstruct_flow_style_v5'}):
            raise ValueError("Unsupported named-field project protocol")
        if flow.math.delimiter_source == "sample" and any(
            ":math-rule:" in s.occurrence_id for s in selections
        ):
            from ..math.sample_constructions import migrate_equation_choices
            from .limits import DocumentLimitError
            from .markdown import parse_markdown

            # Migrate before the first edit, while legacy source offsets still
            # refer to the saved source. Oversized drafts remain recoverable.
            try:
                document = parse_markdown(session, dialect=flow.markdown_dialect, field_blocks=flow.named_fields)
            except DocumentLimitError:
                pass
            else:
                migrate_equation_choices(document, resolver)
        migration_notice = ""
        if manifest["dialect"].endswith("/break-commands-v1"):
            from .break_migration import migrate_v1_breaks

            session, migration_notice = migrate_v1_breaks(session, flow)
        return LoadedDocument(
            session,
            resolver,
            PageProfile(**styles["page"]),
            StyleProfile(**styles["body"]),
            manifest["optimize"],
            sha256(raw).hexdigest(),
            flow,
            reviews,
            migration_notice,
        )
    except (
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        RecursionError,
        zipfile.BadZipFile,
        OverflowError,
        ZeroDivisionError,
    ) as error:
        raise ValueError(f"Invalid document package: {error}") from error


def save_package(
    path: Path,
    session: SourceSession,
    resolver: AssetResolver,
    page: PageProfile,
    style: StyleProfile,
    *,
    optimize=False,
    expected_hash=None,
    flow=None,
    reviews=(),
):
    data = package_bytes(
        session, resolver, page, style, optimize=optimize, flow=flow, reviews=reviews
    )
    return atomic_write(Path(path), data, expected_hash)
