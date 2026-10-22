"""Pinned offline reference-outline experiment; never a production glyph provider.

Run from repo root with the experiment extra installed:
  MPLCONFIGDIR=/tmp/inkstruct-mathtext-cache .venv/bin/python \
      scripts/experiments/mathtext_probe.py --output artifacts/mathtext-probe
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import socket
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

CASES = (
    ("identifier", r"x"),
    ("scripts", r"x_1^2"),
    ("fraction_radical", r"\frac{1.20}{\sqrt{2}}"),
    ("indexed_root", r"\sqrt[3]{8}"),
    ("sum", r"\sum_{i=1}^{3}i"),
    ("integral", r"\int_0^1 x\,dx"),
    ("delimiters", r"\left(\frac{x}{y}\right)^2"),
    ("greek", r"\alpha+\epsilon+\varepsilon"),
    ("unit", r"\mathrm{m^2}"),
    ("text", r"\text{V}"),
    ("matrix", r"\begin{pmatrix}1&2\\3&4\end{pmatrix}"),
    ("explicit_limits", r"\sum\limits_{i=1}^{3}i"),
    ("unknown", r"\notACommand{x}"),
)


def path_data(vertices, codes):
    from matplotlib.path import Path as MplPath

    commands = {MplPath.MOVETO: "M", MplPath.LINETO: "L", MplPath.CURVE3: "Q", MplPath.CURVE4: "C"}
    parts = []
    for values, code in MplPath(vertices, codes).iter_segments(simplify=False, curves=True):
        if code == MplPath.CLOSEPOLY:
            parts.append("Z")
        else:
            if not all(math.isfinite(float(v)) for v in values):
                raise ValueError("Non-finite reference outline")
            parts.append(commands[code] + " ".join(f"{v:.8f}" for v in values))
    return " ".join(parts)


def render(tex, fonts):
    import matplotlib as mpl
    from matplotlib.font_manager import FontProperties
    from matplotlib.ft2font import LoadFlags
    from matplotlib.mathtext import MathTextParser
    from matplotlib.textpath import TextPath

    prop = FontProperties(fname=fonts / "DejaVuSans.ttf", size=12, math_fontfamily="dejavusans")
    settings = dict(mpl.rcParamsDefault)
    settings.pop("backend", None)
    settings.update(
        {
            "mathtext.fontset": "dejavusans",
            "mathtext.fallback": None,
            "text.usetex": False,
            "mathtext.default": "normal",
        }
    )
    with mpl.rc_context(settings):
        # A fresh parser also checks reproducibility without sharing its parse cache.
        parsed = MathTextParser("path").parse("$" + tex + "$", dpi=72, prop=prop)
        width, height, depth = (float(v) for v in parsed[:3])
        assert min(width, height, depth) >= 0 and depth <= height
        baseline = 16 + height - depth
        paths, glyphs = [], []
        for font, size, char, glyph_index, x, y in parsed.glyphs:
            file = Path(font.fname).resolve()
            if file.parent != fonts.resolve():
                raise ValueError("Unpinned external font used: " + str(file))
            font.clear()
            font.set_size(size, 72)
            font.load_glyph(glyph_index, flags=LoadFlags.NO_HINTING)
            vertices, codes = font.get_path()
            translated = [
                (8 + float(x) + float(px), baseline - float(y) - float(py)) for px, py in vertices
            ]
            paths.append(path_data(translated, codes))
            glyphs.append(
                {
                    "font": file.name,
                    "size_pt": float(size),
                    "unicode": int(char),
                    "glyph_index": int(glyph_index),
                    "x_pt": float(x),
                    "y_above_baseline_pt": float(y),
                }
            )
        rules = []
        for x, y, w, h in parsed.rects:
            x, y, w, h = (float(v) for v in (x, y, w, h))
            rules.append({"x_pt": x, "y_above_baseline_pt": y, "width_pt": w, "height_pt": h})
            paths.append(
                f"M{8 + x:.8f} {baseline - y:.8f} L{8 + x + w:.8f} {baseline - y:.8f} L{8 + x + w:.8f} {baseline - y - h:.8f} L{8 + x:.8f} {baseline - y - h:.8f} Z"
            )
        # Visible capability label is also embedded outlines, not an external font.
        label = TextPath(
            (0, 0),
            "REFERENCE ONLY - NOT PLOTTER",
            prop=FontProperties(fname=fonts / "DejaVuSans.ttf", size=5),
        )
        paths.append(
            path_data([(8 + float(x), 9 - float(y)) for x, y in label.vertices], label.codes)
        )
    page_width, page_height = max(110, width + 16), height + 24
    meta = {
        "width_pt": width,
        "height_pt": height,
        "depth_pt": depth,
        "baseline_from_top_pt": baseline,
        "dpi": 72,
        "font_size_pt": 12,
        "glyphs": glyphs,
        "rules": rules,
        "capability": "reference-outline",
        "plotter_ready": False,
    }
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_width * 25.4 / 72:.8f}mm" height="{page_height * 25.4 / 72:.8f}mm" viewBox="0 0 {page_width:.8f} {page_height:.8f}" data-inkstruct-capability="reference-outline">\n'
    svg += "<title>Reference outlines only: not a plotter document</title>\n"
    svg += f'<path d="M8 {baseline:.8f} L{page_width - 8:.8f} {baseline:.8f}" fill="none" stroke="#60a5fa" stroke-width="0.2"/>\n'
    svg += "".join(f'<path d="{d}" fill="#111827"/>\n' for d in paths) + "</svg>\n"
    root = ET.fromstring(svg)
    assert not any(e.tag.rsplit("}", 1)[-1] in {"text", "use", "image"} for e in root.iter())
    assert not any("href" in key for e in root.iter() for key in e.attrib)
    return svg, meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--lock", type=Path, default=Path("configs/experiments/mathtext_probe.lock.json")
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a fresh output directory")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/inkstruct-mathtext-cache")
    lock = json.loads(args.lock.read_text())
    for name, expected in lock["versions"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError("Dependency drift: " + name)
    if platform.python_version() != lock["python"]:
        raise ValueError("Python version drift")
    import matplotlib as mpl
    from matplotlib import ft2font

    fonts = Path(mpl.get_data_path()) / "fonts" / "ttf"
    if ft2font.__freetype_version__ != lock["freetype"]:
        raise ValueError("FreeType version drift")
    for name, expected in lock["fonts"].items():
        if sha256((fonts / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Font drift: " + name)
    report = {
        "backend": "matplotlib-mathtext",
        "lock_sha256": sha256(args.lock.read_bytes()).hexdigest(),
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime": lock,
        "plotter_ready": False,
        "source_span_mapping": False,
        "cases": [],
    }
    attempts = []

    def offline(*args, **kwargs):
        attempts.append("blocked network call")
        raise RuntimeError("Network disabled during reference rendering")

    args.output.mkdir(parents=True)
    with (
        patch.object(socket, "socket", offline),
        patch.object(socket, "create_connection", offline),
        patch.object(socket, "getaddrinfo", offline),
    ):
        for name, tex in CASES:
            try:
                svg, meta = render(tex, fonts)
                svg2, meta2 = render(tex, fonts)
                assert svg == svg2 and meta == meta2
            except ValueError as error:
                report["cases"].append(
                    {"name": name, "source": tex, "status": "unsupported", "error": str(error)}
                )
                continue
            file = args.output / (name + ".svg")
            file.write_text(svg)
            report["cases"].append(
                {
                    "name": name,
                    "source": tex,
                    "status": "rendered",
                    "metrics": meta,
                    "svg_sha256": sha256(svg.encode()).hexdigest(),
                    "repeat_identical": True,
                }
            )
    report["network_attempts"] = attempts
    report["network_guard_enabled"] = True
    report["rc_profile"] = (
        "Pinned Matplotlib defaults; dejavusans, normal math style, no font fallback, no TeX subprocess"
    )
    greek = next(c for c in report["cases"] if c["name"] == "greek")
    report["greek_semantic_comparison"] = {
        "inkstruct_expected_codepoints": [945, 43, 1013, 43, 949],
        "mathtext_codepoints": [g["unicode"] for g in greek["metrics"]["glyphs"]],
        "note": "This backend maps epsilon and varepsilon to the same glyph in the tested profile; InkStruct keeps them distinct",
    }
    report["rendered"] = sum(c["status"] == "rendered" for c in report["cases"])
    report["unsupported"] = len(CASES) - report["rendered"]
    (args.output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in ["backend", "rendered", "unsupported", "plotter_ready", "network_attempts"]
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
