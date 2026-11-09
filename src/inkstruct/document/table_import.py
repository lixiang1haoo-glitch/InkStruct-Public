"""Read legacy .inktable projects into new portable documents without overwriting them."""

import json
from hashlib import sha256
from pathlib import Path

from ..assets.resolver import AssetResolver, SelectedAsset
from ..assets.symbol_provider import SymbolProvider
from ..table_editor.core import Settings, parse_table
from ..table_editor.samples import load_sample_zip
from .editing import SourceSession
from .markdown import parse_markdown
from .package import LoadedDocument
from .schema import PageProfile, StyleProfile
from .styles import FlowStyle
from .table_style import TableStyle, calibrate_tables


def import_table_project(path: Path) -> LoadedDocument:
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise ValueError("Legacy table project exceeds 1 MB")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
        if value["schema_version"] != "inkstruct_table_v1" or not isinstance(value["html"], str):
            raise ValueError("Unsupported legacy table project")
        source = value["html"]
        old_table = parse_table(source)
        settings = Settings(**value["settings"])
        route = value.get("routing", {})
        if not isinstance(route, dict) or any(
            type(route.get(k, False)) is not bool for k in ("optimize", "allow_reverse")
        ):
            raise ValueError("Invalid legacy routing settings")
        style = TableStyle(
            width_mm=settings.table_width,
            min_row_height_mm=settings.row_height,
            digit_height_mm=settings.digit_height,
            stroke_width_mm=settings.stroke_width,
            padding_top_mm=settings.padding,
            padding_right_mm=settings.padding,
            padding_bottom_mm=settings.padding,
            padding_left_mm=settings.padding,
            width_mode="ratio" if settings.column_weights else "equal",
            columns=settings.column_weights,
            fixed_row_height=True,
            repeat_header=False,
            numeric_spacing="legacy-ink",
        )
        if style.columns and len(style.columns) != old_table.columns:
            raise ValueError("Legacy column weights do not match the table")
        page = PageProfile(settings.page_width, settings.page_height, settings.margin)
        flow = FlowStyle(table=style)
        reference, samples, bank, seed = value.get("samples"), None, None, 0
        if reference is not None:
            if (
                not isinstance(reference, dict)
                or type(reference["seed"]) is not int
                or not 0 <= reference["seed"] <= 2147483647
            ):
                raise ValueError("Invalid legacy sample seed")
            seed = reference["seed"]
            sample_path = path.parent / reference["path"]
            bank = load_sample_zip(sample_path)
            if bank.sha256 != reference["sha256"]:
                raise ValueError("Legacy sample archive changed; restore the recorded archive")
            samples = SymbolProvider.from_zip(sample_path)
            if samples.archive_hash != bank.sha256:
                raise ValueError("Sample archive changed while importing")
            flow = calibrate_tables(flow, samples)
        session = SourceSession(source)
        document = parse_markdown(session)
        if (
            len(document.nodes) != 1
            or document.nodes[0].kind != "table"
            or any(d.severity == "error" for d in document.diagnostics)
        ):
            raise ValueError("Legacy source cannot be mapped to one supported table")
        resolver = AssetResolver(symbols=samples, builtin_numbers=True, seed=seed)
        if bank:
            legacy = bank.select(seed)
            for occurrence in document.occurrences:
                if occurrence.text.isspace():
                    continue
                legacy[occurrence.text]
                selected = legacy.trace[-1]["sample_id"]
                candidates = resolver.pools[occurrence.text]
                glyph = next((g for g in candidates if g.sample_id == selected), None)
                if selected == "builtin:decimal-point":
                    glyph = next(g for g in candidates if g.writer_id == "builtin")
                if glyph is None:
                    raise ValueError("Legacy selected specimen is unavailable")
                resolver.selections[occurrence.occurrence_id] = SelectedAsset(
                    occurrence.occurrence_id,
                    occurrence.text,
                    glyph.asset_id,
                    glyph.sample_id,
                    glyph.metrics_key,
                )
        # A new .inkdoc is required on save: this hash is provenance, not permission
        # to replace the legacy project with a different format.
        return LoadedDocument(
            session,
            resolver,
            page,
            StyleProfile(),
            route.get("optimize", False),
            sha256(raw).hexdigest(),
            flow,
        )
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError(f"Invalid legacy table project: {error}") from error
