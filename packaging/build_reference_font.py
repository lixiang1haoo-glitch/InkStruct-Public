"""Build the redistributable reference medians from the locked structure database."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from inkstruct.fonts.exchange_codec import digest, encode, verify
from inkstruct.fonts.reference import REFERENCE_FILE, REFERENCE_ID, REFERENCE_NAME
from inkstruct.structures import StructureRepository


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
        write("index.json", encode(index))
        licenses = root / "third_party/makemeahanzi"
        for name in ("COPYING", "APL/english/ARPHICPL.TXT", "APL/zh_CN.UTF-8/ARPHICPL.TXT"):
            write("extensions/licenses/" + name, (licenses / name).read_bytes())
        write("extensions/source.txt", (
            "Reference stroke medians from Make Me a Hanzi (Arphic Public License).\n"
            "https://github.com/skishore/makemeahanzi/tree/bddc96d41bef78427ed0e034e9f7e31d71fd1b92\n"
            "InkStruct converts normalized reference medians to baseline-relative inkfont v1 strokes.\n"
        ).encode())
        manifest = {"format": "inkfont", "format_version": 1, "name": REFERENCE_NAME,
                    "font_id": REFERENCE_ID, "members": members}
        archive.writestr(ZipInfo("manifest.json"), encode(manifest), compress_type=ZIP_DEFLATED)
    return verify(target)

