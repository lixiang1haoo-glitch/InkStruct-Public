"""Occurrence-based selection and resource gaps for generated and sampled glyphs."""

from __future__ import annotations

import csv
import io
from copy import copy
from dataclasses import asdict, dataclass, replace
from types import MappingProxyType

from ..document.schema import Occurrence, digest
from ..fonts.identity import release_identity
from ..symbol_capture import symbol_info
from .glyph_provider import GlyphProvider, is_han
from .symbol_provider import ResolvedGlyph, SymbolProvider, from_generated

SELECTION_VERSION = "occurrence-choice-v1"


@dataclass(frozen=True)
class SelectedAsset:
    occurrence_id: str
    character: str
    asset_id: str
    sample_id: str
    metrics_key: str
    selection_version: str = SELECTION_VERSION
    requested_style: str = ""
    resolved_style: str = ""
    warning_accepted: bool = False


class AssetResolver:
    def __init__(
        self,
        generated: GlyphProvider | None = None,
        symbols: SymbolProvider | None = None,
        *,
        seed=0,
        selections=(),
        builtin_numbers=False,
        embedded=(),
        font_identity=None,
        indexed=None,
    ):
        selections = tuple(selections)
        pools = {
            c: (from_generated(g),) for c, g in (generated.assets.items() if generated else ())
        }
        if symbols:
            pools.update(symbols.pools)
        for glyph in embedded:
            current = pools.setdefault(glyph.character, ())
            if not any(
                g.asset_id == glyph.asset_id and g.metrics_key == glyph.metrics_key for g in current
            ):
                pools[glyph.character] = (*current, glyph)
        if builtin_numbers:
            from .builtin import numeric_assets

            for c, glyph in numeric_assets().items():
                pools.setdefault(c, (glyph,))
        from .derived_symbols import supplement_recorded_symbols

        pools.update(supplement_recorded_symbols(pools, selections))
        self._pools = pools
        self.pools = MappingProxyType(pools)
        self.indexed = indexed
        self.seed = seed
        self.font_identity = font_identity
        self.selections = {s.occurrence_id: s for s in selections}
        if len(self.selections) != len(selections):
            raise ValueError("Duplicate selected occurrence")
        resource_ids = {c: [(g.asset_id, g.metrics_key) for g in v] for c, v in pools.items()}
        self.resource_key = digest(resource_ids if indexed is None else [
            resource_ids, indexed.token[2], tuple(indexed.pools),
        ])

    def copy_choices(self):
        """Copy mutable choices and pool membership while sharing immutable glyphs."""
        result = copy(self)
        result._pools = self._pools.copy()
        result.pools = MappingProxyType(result._pools)
        result.selections = self.selections.copy()
        return result

    def candidate_index(self, character):
        records = self.indexed.pools.get(character) if self.indexed else None
        return records or self.pools.get(character, ())

    def candidate_pool(self, character):
        records = self.indexed.pools.get(character) if self.indexed else None
        if not records:
            return self.pools.get(character, ())
        with self.indexed.opened():
            return tuple(self.indexed.load(record) for record in records)

    def resolve(self, occurrence: Occurrence, *, letter_style="upright") -> ResolvedGlyph:
        pool = self.pools.get(occurrence.text, ())
        indexed = self.indexed.pools.get(occurrence.text, ()) if self.indexed else ()
        if not pool and not indexed:
            raise ValueError(f"Missing glyph resource: {occurrence.text!r}")
        previous = self.selections.get(occurrence.occurrence_id)
        if previous and (not previous.requested_style or previous.requested_style == letter_style):
            if (
                previous.character != occurrence.text
                or previous.selection_version != SELECTION_VERSION
            ):
                raise ValueError("Selected asset identity is incompatible")
            for glyph in pool:
                if (glyph.asset_id, glyph.sample_id, glyph.metrics_key) == (
                    previous.asset_id,
                    previous.sample_id,
                    previous.metrics_key,
                ):
                    return glyph
            for candidate in indexed:
                if (candidate.sample_id, candidate.metrics_key) == (previous.sample_id, previous.metrics_key):
                    glyph = self.indexed.load(candidate)
                    if glyph.asset_id == previous.asset_id:
                        self._pools[occurrence.text] = (*pool, glyph)
                        return glyph
            raise ValueError(
                "Previously selected asset or calibration is unavailable; no reselection"
            )
        stored = pool
        if indexed:
            pool = indexed
        if self.font_identity and not indexed:
            pool = tuple(g for g in pool if not g.font_metadata
                         or release_identity(g.font_metadata['identity']) in (None, self.font_identity))
            if not pool:
                raise ValueError(f"Missing glyph resource: {occurrence.text!r}")
        if occurrence.text in {"ℏ", "．"}:
            # Historical frozen choices returned above remain valid. New choices
            # prefer supplied recordings, then recorded derivations, then builtin ink.
            from .derived_symbols import is_runtime_derived
            recorded = tuple(g for g in pool if g.provider_version != "builtin-numeric-em-v1")
            if recorded:
                pool = recorded
            supplied = tuple(g for g in pool if not is_runtime_derived(g))
            if supplied:
                pool = supplied
        from ..fonts.core import latin
        styled = latin(occurrence.text) or (occurrence.text == "ℏ" and any(
            g.font_metadata and g.font_metadata["record"]["letter_style"] in {"upright", "italic", "unspecified"}
            for g in pool))
        requested = letter_style if styled and any(g.font_metadata for g in pool) else ""
        if requested:
            def category(g):
                return g.font_metadata["record"]["letter_style"] if g.font_metadata else "unspecified"
            matching = tuple(g for g in pool if category(g) == requested)
            if not matching:
                matching = tuple(g for g in pool if category(g) == "unspecified") or pool
            pool = matching
        if any(g.font_metadata for g in pool):
            enabled = tuple(g for g in pool if not g.font_metadata or (
                g.font_metadata["record"]["enabled"] and
                g.font_metadata["summary"]["review_status"] not in {"rejected", "needs_review"}))
            if not enabled:
                raise ValueError("No enabled glyph candidate")
            priority = min(g.font_metadata["record"]["priority"] if g.font_metadata else 2 for g in enabled)
            pool = tuple(g for g in enabled if (g.font_metadata["record"]["priority"] if g.font_metadata else 2) == priority)
            pool = tuple(sorted(pool, key=lambda g:g.sample_id))
        key = digest([SELECTION_VERSION, self.seed, occurrence.occurrence_id, occurrence.text] + ([requested] if requested else []))
        glyph = pool[int(key[:16], 16) % len(pool)]
        if indexed:
            sample_id = glyph.sample_id
            existing = next((g for g in stored if g.sample_id == sample_id), None)
            glyph = existing if existing is not None else self.indexed.load(glyph)
            if existing is None:
                self._pools[occurrence.text] = (*stored, glyph)
        self.selections[occurrence.occurrence_id] = SelectedAsset(
            occurrence.occurrence_id,
            occurrence.text,
            glyph.asset_id,
            glyph.sample_id,
            glyph.metrics_key,
            requested_style=requested,
            resolved_style=(glyph.font_metadata["record"]["letter_style"] if glyph.font_metadata else ""),
        )
        return glyph

    def usage_warnings(self, *, pending_only=False, occurrence_ids=None):
        records = {}
        lookup = {g.asset_id:g for pool in self.pools.values() for g in pool}
        for choice in self.selections.values():
            if occurrence_ids is not None and choice.occurrence_id not in occurrence_ids:
                continue
            if pending_only and choice.warning_accepted:
                continue
            glyph = lookup.get(choice.asset_id)
            if not glyph or not glyph.font_metadata:
                continue
            summary = glyph.font_metadata["summary"]
            reasons = list(summary.get("warnings", []))
            required = ('作者来源记录不完整' if summary['unknown_strokes'] else
                        '含参考替代笔画' if summary['reference_strokes'] else '')
            if required and required not in reasons:
                reasons.append(required)
            if choice.requested_style and choice.requested_style != choice.resolved_style:
                names = {"upright":"正体", "italic":"斜体", "unspecified":"未分类"}
                reasons.append(f"需要{names[choice.requested_style]}，实际使用{names.get(choice.resolved_style, choice.resolved_style)}")
            if reasons:
                key = (choice.character, choice.sample_id, choice.requested_style)
                item = records.setdefault(key, {"character":choice.character,"candidate_id":choice.sample_id,
                    "reasons":reasons,"reference_strokes":summary["reference_strokes"],
                    "unknown_strokes":summary["unknown_strokes"],"gaps":summary["gaps"],"occurrences":0})
                item["occurrences"] += 1
        return list(records.values())

    def accept_usage_warnings(self):
        self.selections = {k:replace(s, warning_accepted=True) for k,s in self.selections.items()}

    def selection_records(self):
        records = []
        for choice in sorted(self.selections.values(), key=lambda s: s.occurrence_id):
            record = asdict(choice)
            if not choice.requested_style and not choice.resolved_style and not choice.warning_accepted:
                for key in ("requested_style", "resolved_style", "warning_accepted"):
                    record.pop(key)
            records.append(record)
        return records

    def gaps(self, occurrences):
        missing = {}
        expanded = []
        for occurrence in occurrences:
            if (occurrence.text == "ℏ" and "ℏ" not in self.pools
                    and occurrence.occurrence_id not in self.selections):
                # Capture the missing real sources, never demand an independently
                # drawn hbar when its construction is already explicitly defined.
                sources = ("h", "−" if "−" in self.pools or "-" not in self.pools else "-")
                unavailable = []
                for char in sources:
                    source = replace(occurrence, text=char,
                                     occurrence_id=occurrence.occurrence_id + ":hbar-source:" + str(ord(char)))
                    try:
                        self.resolve(source, letter_style="italic" if char == "h" else "upright")
                    except ValueError:
                        unavailable.append(source)
                expanded.extend(unavailable or (occurrence,))
            else:
                expanded.append(occurrence)
        restore = set()
        for occurrence in expanded:
            text = occurrence.text
            if text.isspace():
                continue
            try:
                previous = self.selections.get(occurrence.occurrence_id)
                requested = previous.requested_style if previous and previous.requested_style else "upright"
                self.resolve(occurrence, letter_style=requested)
            except ValueError as error:
                if occurrence.occurrence_id in self.selections:
                    restore.add(text)
                record = missing.setdefault(
                    text, {"character": text, "reason": str(error), "source_ranges": []}
                )
                record["source_ranges"].append(asdict(occurrence.span))
        for text, record in missing.items():
            if text in self.pools or (self.indexed and text in self.indexed.pools) or text in restore:
                record["action"] = "restore-selected-resource"
                continue
            try:
                record["capture"] = symbol_info(text)
                record["action"] = "symbol-capture"
            except ValueError:
                record["action"] = "generate-han" if is_han(text) else "unsupported-cluster"
        return list(missing.values())


def gap_capture_csv(gaps) -> str:
    """Collector-compatible CSV: unsupported clusters and Han stay in the JSON report."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["character", "repeats", "category", "codepoint", "unicode_name"])
    from ..punctuation import capture_character
    seen = set()
    for gap in gaps:
        if gap["action"] == "symbol-capture":
            character = capture_character(gap['character'])
            if character in seen:
                continue
            seen.add(character)
            info = symbol_info(character)
            writer.writerow(
                [character, 5, info["category"], info["codepoint"], info["unicode_name"]]
            )
    return stream.getvalue()
