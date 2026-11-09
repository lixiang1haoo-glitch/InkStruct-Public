"""Explicit single-line numeric fallback shared with the standalone table tool."""

from dataclasses import replace

from ..document.schema import digest
from ..table_editor.core import BUILTIN_GLYPHS
from .glyph_provider import GlyphMetrics
from .symbol_provider import ResolvedGlyph


def numeric_assets():
    assets = {}
    for character, glyph in BUILTIN_GLYPHS.items():
        strokes = tuple(tuple((x * 0.7, 0.18 + y * 0.7) for x, y in p) for p in glyph.strokes)
        metrics = GlyphMetrics(glyph.advance * 0.7, 0.88, 0.88, 0.12)
        identity = digest(["builtin-numeric-em-v1", character, strokes])
        assets[character] = ResolvedGlyph(
            identity,
            character,
            f"builtin:{character}",
            "builtin",
            strokes,
            metrics,
            "builtin-numeric-em-v1",
            b"{}",
            "builtin-numeric-em-v1",
        )
    # Explicit width variant of the existing decimal point. Keep both Unicode
    # identities so portable documents can validate and reopen either form.
    dot = assets["."]
    assets["．"] = replace(dot,
        asset_id=digest(["builtin-numeric-em-v1", "．", dot.strokes]),
        character="．", sample_id="builtin:．",
        metrics=replace(dot.metrics, advance=max(1.0, dot.metrics.advance)))
    return assets
