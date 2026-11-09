"""Small, explicit recorded-symbol additions for already installed fonts.

Derived descriptors are ordinary validated font-core snapshots, so documents keep
all original samples plus the complete construction provenance when saved.
"""

import copy
from dataclasses import asdict

from ..fonts.core import decode, resolved_candidate, semantic_hash, trajectory_hashes
from ..fonts.symbol_rules import _recorded_hbar_constructions

POLICY = "runtime-recorded-symbols-v1"


def _source(glyph):
    if glyph.font_core:
        core = glyph.font_core
        return core["record"], core["trajectory"], core["metrics"], core["summary"]
    value = decode(glyph.original_json)
    if value.get("schema_version") != "inkstruct_symbol_sample_v1":
        return None
    from ..fonts.importer import make_symbol

    trajectory, _, summary = make_symbol(glyph.original_json, value)
    # Custom profiles must not be silently replaced with the default frame.
    if tuple(tuple((p["x"], p["y"]) for p in st["points"])
             for st in trajectory["strokes"]) != glyph.strokes:
        return None
    metrics = asdict(glyph.metrics)
    record = {"candidate_id": glyph.sample_id, "character": glyph.character,
              "enabled": True, "priority": 0,
              "letter_style": value.get("variant", {}).get("letter_style", "unspecified"),
              **trajectory_hashes(trajectory), "metrics_id": semantic_hash(metrics),
              "source_summary_hash": semantic_hash(summary)}
    return record, trajectory, metrics, summary


def _descriptor(target, trajectory, metrics, summary, key, writer, *, letter_style="not_applicable", priority=0):
    hashes = trajectory_hashes(trajectory)
    record = {"candidate_id": POLICY + ":" + key, "character": target,
              "file": "glyphs/" + hashes["trajectory_hash"] + ".json", **hashes,
              "metrics_id": semantic_hash(metrics), "source_summary_hash": semantic_hash(summary),
              "letter_style": letter_style, "style_evidence": "explicit-construction",
              "enabled": True, "priority": priority}
    return resolved_candidate(record, trajectory, metrics, summary,
                              {"writer_alias": writer, "construction_policy": POLICY,
                               "construction_id": key})


def _key(glyph):
    return glyph.asset_id, glyph.sample_id, glyph.metrics_key


def is_runtime_derived(glyph):
    return bool(glyph.font_core and
                glyph.font_core["record"]["candidate_id"].startswith(POLICY + ":"))


def supplement_recorded_symbols(pools, selections=()):
    """Prefer supplied targets, retaining every explicitly frozen descriptor."""
    additions = {}
    missing_frozen = {}
    for char in ("．", "ℏ"):
        present = {_key(g) for g in pools.get(char, ())}
        missing_frozen[char] = {
            (s.asset_id, s.sample_id, s.metrics_key) for s in selections
            if s.character == char and s.sample_id.startswith(POLICY + ":")
            and (s.asset_id, s.sample_id, s.metrics_key) not in present}

    def append(target, glyph):
        current = additions.get(target, tuple(pools.get(target, ())))
        if _key(glyph) not in {_key(g) for g in current}:
            additions[target] = (*current, glyph)

    fullwidth = pools.get("．", ())
    builtin_fullwidth = all(g.provider_version == "builtin-numeric-em-v1" for g in fullwidth)
    if not fullwidth or builtin_fullwidth or missing_frozen["．"]:
        dots = []
        for glyph in pools.get(".", ()):
            if glyph.provider_version == "builtin-numeric-em-v1":
                if not fullwidth:
                    from .builtin import numeric_assets
                    builtin = numeric_assets()
                    if glyph == builtin["."]:
                        dots.append(builtin["．"])
                continue
            loaded = _source(glyph)
            if loaded is None:
                continue
            record, original, metrics, summary = loaded
            if (not record["enabled"] or summary.get("review_status") in {"rejected", "needs_review"}
                    or summary.get("source_kind") != "recorded"):
                continue
            trajectory, metrics, summary = map(copy.deepcopy, (original, metrics, summary))
            trajectory["character"] = "．"
            metrics["advance"] = max(1.0, metrics["advance"])
            if "optical_layout_frame" in summary:
                frame = summary["optical_layout_frame"]
                frame["metrics"]["advance"] = max(1.0, frame["metrics"]["advance"])
            from ..punctuation import POLICY as SHARING_POLICY
            sharing = {"policy": SHARING_POLICY, "source_character": ".",
                       "source_sample_id": glyph.sample_id, "source_asset_id": glyph.asset_id,
                       "source_metrics_key": glyph.metrics_key}
            summary.update(shared_punctuation=sharing, review_status="unreviewed",
                           evidence_scope="same recorded dot; explicit fullwidth punctuation reuse")
            key = semantic_hash([POLICY, "．", sharing])
            dots.append(_descriptor("．", trajectory, metrics, summary, key, glyph.writer_id,
                                    priority=record.get("priority", 0)))
        for glyph in dots:
            if not fullwidth or builtin_fullwidth or _key(glyph) in missing_frozen["．"]:
                append("．", glyph)
    if (("ℏ" not in pools or missing_frozen["ℏ"])
            and pools.get("h") and (pools.get("−") or pools.get("-"))):
        # Keep every h style available, and never cross authors when fonts mix.
        for writer in sorted({glyph.writer_id for glyph in pools["h"]}):
            records, values, sources = [], {}, {}
            for char in ("h", "−", "-"):
                for glyph in sorted(pools.get(char, ()), key=lambda g: (g.sample_id, g.asset_id)):
                    if glyph.writer_id != writer:
                        continue
                    loaded = _source(glyph)
                    if loaded is None:
                        continue
                    record, trajectory, metrics, summary = loaded
                    records.append(record)
                    values[id(record)] = (trajectory, metrics, summary)
                    signature = (record["candidate_id"], record["trajectory_hash"],
                                 record["metrics_id"], record["source_summary_hash"])
                    sources[signature] = glyph
            for trajectory, metrics, summary, _ in _recorded_hbar_constructions(
                    records, lambda r, values=values: values[id(r)]):
                construction = summary["symbol_construction"]
                chosen = [sources[(r["candidate_id"], r["trajectory_hash"], r["metrics_id"],
                                   r["source_summary_hash"])] for r in construction["sources"]]
                construction["source_assets"] = [
                    {"asset_id": glyph.asset_id, "sample_id": glyph.sample_id,
                     "metrics_key": glyph.metrics_key} for glyph in chosen]
                construction.pop("construction_id", None)
                construction["construction_id"] = semantic_hash(construction)
                key = semantic_hash([POLICY, "ℏ", construction])
                glyph = _descriptor("ℏ", trajectory, metrics, summary, key, writer,
                                    letter_style=construction["base_letter_style"],
                                    priority=((chosen[0].font_core["record"].get("priority", 0)
                                               if chosen[0].font_core else 0)
                                              + int(chosen[1].character == "-")))
                if "ℏ" not in pools or _key(glyph) in missing_frozen["ℏ"]:
                    append("ℏ", glyph)
    return additions
