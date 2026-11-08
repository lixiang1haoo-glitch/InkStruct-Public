"""Compare published fonts to actual frozen generator outputs, point for point."""

import argparse
import json
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from inkstruct.assets.glyph_provider import GlyphMetrics
from inkstruct.fonts.core import FontPackage, decode, encoded, sha, write_archive
from inkstruct.fonts.importer import (
    generated_records,
    make_symbol,
    public_development,
    symbol_records,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fonts", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for writer in ("user_001", "scx", "mjb", "wsq"):
        user = args.fonts / (writer + "-0.1.inkfont")
        dev = args.fonts / (writer + "-0.1-developer.inkfont")
        f = FontPackage(user)
        d = FontPackage(dev)
        assert f.manifest["core_hash"] == d.manifest["core_hash"]
        assert f.records == d.records and f.metrics == d.metrics and f.provenance == d.provenance
        kinds = Counter()
        points = 0
        chars = 0
        symbol_count = 0
        with zipfile.ZipFile(user) as z:
            for glyph, row, payload, protocol in generated_records(args.run, writer):
                record = next(
                    r
                    for r in f.pools[glyph["character"]]
                    if f.provenance[r["candidate_id"]]["source_kind"] == "generated"
                )
                core = decode(z.read(record["file"]))
                for original, restored in zip(glyph["strokes"], core["strokes"], strict=True):
                    assert original["points"] == restored["points"], (writer, glyph["character"])
                    points += len(original["points"])
                assert f.metrics[record["candidate_id"]] == asdict(GlyphMetrics())
                summary = f.provenance[record["candidate_id"]]
                assert summary["reference_strokes"] == [x["order"] for x in row["missing"]]
                kinds.update(s["kind"] for s in row["stroke_sources"])
                chars += 1
                if chars % 2000 == 0:
                    print(writer, chars, flush=True)
            if writer == "user_001":
                for raw, value in symbol_records(args.symbols):
                    t, m, s = make_symbol(raw, value)
                    # Identity is source SHA, so reordered ZIP entries cannot reassign samples.
                    import uuid

                    cid = str(uuid.uuid5(uuid.UUID(f.manifest["font_id"]), sha(raw)))
                    record = next(
                        r for r in f.pools[value["character"]] if r["candidate_id"] == cid
                    )
                    assert decode(z.read(record["file"])) == t
                    assert f.metrics[cid] == m and f.provenance[cid] == s
                    symbol_count += 1
        # Publish a scrubbed developer edition; retain the original local audit artifact untouched.
        public = args.fonts / (writer + "-0.1-share-developer.inkfont")
        if not public.exists():
            with tempfile.TemporaryDirectory() as temporary, zipfile.ZipFile(dev) as z:
                members = {}
                for i, n in enumerate(d.manifest["members"]):
                    raw = z.read(n)
                    if n.startswith("development/") and n.endswith(".json"):
                        raw = encoded(public_development(decode(raw)))
                    p = Path(temporary) / str(i)
                    p.write_bytes(raw)
                    members[n] = p
                m = {
                    k: v
                    for k, v in d.manifest.items()
                    if k not in ("members", "core_members", "core_hash", "content_hash")
                }
                import uuid

                m["package_id"] = str(uuid.uuid4())
                m["derived_from_package"] = {
                    "package_id": d.manifest["package_id"],
                    "content_hash": d.manifest["content_hash"],
                }
                m["privacy"] = "host paths and capture/device metadata omitted"
                write_archive(public, members, m)
        p = FontPackage(public)
        assert p.manifest["core_hash"] == f.manifest["core_hash"]
        results.append(
            {
                "writer": writer,
                "generated_characters": chars,
                "generated_points_exact": points,
                "recorded_symbol_candidates_exact": symbol_count,
                "source_kinds": dict(kinds),
                "developer_user_candidates_metrics_provenance_equal": True,
                "user_package_sha256": sha(user.read_bytes()),
                "developer_share_sha256": sha(public.read_bytes()),
                "developer_share": str(public),
                "core_hash": f.manifest["core_hash"],
            }
        )
        (args.fonts / "source-roundtrip.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2)
        )
        print("EXACT", writer, chars, points, flush=True)


if __name__ == "__main__":
    main()
