import copy
import gzip
import json
from pathlib import Path

import pytest

from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font
from inkstruct.generation_parallel import verify_row
from inkstruct.generation_variants import POOL_VERSION
from inkstruct.generation_workflow import write
from inkstruct.samples import sha256_file
from test_document_layout import glyph


CHARACTER = "人"
WRITER = "test"
PROFILE = "a" * 64


def payload_for(donor, delta):
    value = glyph()
    value["strokes"][0]["points"][0]["x"] += delta
    provenance = {
        str(i): {"character": donor, "sample_id": f"{donor}-sample", "source_sha256": "b" * 64,
                 "source_stroke_id": stroke["standard_stroke_id"], "kind": "author_complete_component",
                 "transform": {"sx": 1.0, "sy": 1.0, "tx": 0.0, "ty": 0.0}}
        for i, stroke in enumerate(value["strokes"])
    }
    sources = [{"order": stroke["order"], "standard_id": stroke["standard_stroke_id"],
                **provenance[str(i)]} for i, stroke in enumerate(value["strokes"])]
    return {"glyph": value, "source_profile_sha256": PROFILE, "missing": [], "author_only_ready": True,
            "checks": {"protocol": [], "source_integrity": []}, "provenance": provenance,
            "stroke_sources": sources, "variant_admission": {"accepted": True}}


def write_run(run, payload, *, limit, count=None):
    stem = run / WRITER / f"{ord(CHARACTER):04X}"
    stem.parent.mkdir(parents=True, exist_ok=True)
    packed = stem.with_suffix(".json.gz")
    packed.write_bytes(gzip.compress(json.dumps(payload).encode(), mtime=0))
    row = {"writer": WRITER, "character": CHARACTER, "status": "complete", "source_strokes": 2,
           "reference_strokes": 0, "files": {str(packed.relative_to(run)): sha256_file(packed)},
           **{k: payload[k] for k in ("author_only_ready", "stroke_sources", "missing", "checks")}}
    if count is not None:
        row["candidate_count"] = count
    write(stem.with_suffix(".json"), row)
    protocol = {"writers": [WRITER], "characters": [CHARACTER], "profile": {"sha256": PROFILE}}
    if limit > 1:
        protocol["candidate_pool"] = {"version": POOL_VERSION, "limit": limit, "attempt_limit": 16}
    write(run / "protocol.json", protocol)
    return row


def test_validated_candidates_all_reach_the_font_and_preserve_primary_id(tmp_path):
    original = payload_for("信", 0)
    new = copy.deepcopy(original)
    new["candidate_pool"] = {"version": POOL_VERSION, "alternatives": [
        payload_for("你", .02), payload_for("他", .03)]}
    run = tmp_path / "new"
    row = write_run(run, new, limit=4, count=3)
    verify_row(run, WRITER, CHARACTER, row, PROFILE, candidate_limit=4)
    write_run(tmp_path / "old", original, limit=1)
    old, updated = tmp_path / "old.inkfont", tmp_path / "new.inkfont"
    for path, folder in ((old, "old"), (updated, "new")):
        build_font(path, writer=WRITER, name="same font", run=tmp_path / folder)
    before, after = FontPackage(old), FontPackage(updated)
    assert after.verify()["candidates"] == 3
    assert before.records[0] in after.records
    assert len({record["geometry_hash"] for record in after.records}) == 3


@pytest.mark.parametrize("damage", ["same_geometry", "wrong_writer", "missing_source", "same_character",
                                    "unaccepted", "wrong_profile", "wrong_count", "missing_pool"])
def test_corrupt_candidate_pool_never_commits_or_creates_a_font(tmp_path, damage):
    primary = payload_for("信", 0)
    alt = payload_for("你", .02)
    primary["candidate_pool"] = {"version": POOL_VERSION, "alternatives": [alt]}
    count = 2
    if damage == "same_geometry":
        alt["glyph"] = primary["glyph"]
    elif damage == "wrong_writer":
        alt["glyph"]["writer_id"] = "different"
    elif damage == "missing_source":
        del alt["provenance"]["1"]
    elif damage == "same_character":
        alt["provenance"]["0"]["character"] = CHARACTER
        alt["stroke_sources"][0]["character"] = CHARACTER
    elif damage == "unaccepted":
        alt["variant_admission"]["accepted"] = False
    elif damage == "wrong_profile":
        alt["source_profile_sha256"] = "c" * 64
    elif damage == "wrong_count":
        count = 3
    elif damage == "missing_pool":
        del primary["candidate_pool"]
    run = tmp_path / "run"
    row = write_run(run, primary, limit=4, count=count)
    with pytest.raises(ValueError):
        verify_row(run, WRITER, CHARACTER, row, PROFILE, candidate_limit=4)
    font = tmp_path / "bad.inkfont"
    with pytest.raises(ValueError):
        build_font(font, writer=WRITER, name="bad", run=run)
    assert not font.exists()
