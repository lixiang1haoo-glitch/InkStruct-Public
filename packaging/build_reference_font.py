"""Build the reference medians and the approved non-Han handwriting subset."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from inkstruct.assets.glyph_provider import is_han
from inkstruct.fonts.exchange_codec import CheckedArchive, EXTENSIONS, digest, encode, verify
from inkstruct.fonts.reference import REFERENCE_FILE, REFERENCE_ID, REFERENCE_NAME
from inkstruct.structures import StructureRepository


def add_symbols(root, index, write):
    lock = json.loads((root / "packaging/reference-symbols.lock.json").read_bytes())
    with (root / lock["path"]).open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != lock["sha256"]:
            raise ValueError("参考字体的补充字形来源与构建清单不符")
        with ZipFile(file) as archive:
            source = CheckedArchive(archive)
            ordered = {ch: ids for ch, ids in source.json("index.json").items()
                       if ch not in index and not is_han(ch)}
            candidates = [cid for ids in ordered.values() for cid in ids]
            if (len(ordered), len(candidates)) != (lock["characters"], lock["candidates"]):
                raise ValueError("参考字体的补充字形数量与构建清单不符")
            for cid in candidates:
                member = f"glyphs/{cid}.json"
                write(member, source.read(member))
            for kind, fields in (("provenance", ("source_kind", "letter_style", "trajectory_digest")),
                                 ("math", ("math_axis_em", "trajectory_digest"))):
                member = EXTENSIONS[kind]
                entries = source.json(member)["entries"]
                selected = {cid: {k: entries[cid][k] for k in fields if k in entries[cid]}
                            for cid in candidates if cid in entries}
                write(member, encode({"schema_version": 1, "entries": selected}))
            index.update(ordered)


def build_reference_font(root: Path, bundle: Path):
    repository = StructureRepository(root / "artifacts/structures/characters.sqlite3")
    target = bundle / REFERENCE_FILE
    index, members = {}, {}
    with ZipFile(target, "x") as archive:
        def write(name, data):
            info = ZipInfo(name)  # Stable timestamps across builds.
            archive.writestr(info, data, compress_type=ZIP_DEFLATED)
            members[name] = {"bytes": len(data), "sha256": digest(data)}

        for graph in repository.iter_graphs():
            cid = f"u{ord(graph.character):x}"
            index[graph.character] = [cid]
            # Structure coordinates use a top-left em; inkfont uses the writing baseline.
            strokes = [[[x, round(y - 0.88, 8)] for x, y in stroke.median] for stroke in graph.strokes]
            write(f"glyphs/{cid}.json", encode({"strokes": strokes}))
        add_symbols(root, index, write)
        write("index.json", encode(index))
        licenses = root / "third_party/makemeahanzi"
        for name in ("COPYING", "APL/english/ARPHICPL.TXT", "APL/zh_CN.UTF-8/ARPHICPL.TXT"):
            write("extensions/licenses/" + name, (licenses / name).read_bytes())
        write("extensions/source.txt", (
            "Non-Han handwriting supplied by user_001. Original stroke order, letter styles and math axes retained.\n"
            "Reference stroke medians from Make Me a Hanzi (Arphic Public License).\n"
            "https://github.com/skishore/makemeahanzi/tree/bddc96d41bef78427ed0e034e9f7e31d71fd1b92\n"
            "InkStruct converts normalized reference medians to baseline-relative inkfont v1 strokes.\n"
        ).encode())
        manifest = {"format": "inkfont", "format_version": 1, "name": REFERENCE_NAME,
                    "font_id": REFERENCE_ID, "members": members}
        archive.writestr(ZipInfo("manifest.json"), encode(manifest), compress_type=ZIP_DEFLATED)
    return verify(target)

