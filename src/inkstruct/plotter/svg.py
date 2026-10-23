from __future__ import annotations

from xml.etree import ElementTree as ET

from .schema import PlotPage


def page_svg(page: PlotPage) -> str:
    """Strict machine dialect: path children only, absolute M/L, millimetres."""
    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": f"{page.width_mm:.6f}mm",
            "height": f"{page.height_mm:.6f}mm",
            "viewBox": f"0 0 {page.width_mm:.6f} {page.height_mm:.6f}",
        },
    )
    for stroke in page.strokes:
        d = " ".join(
            f"{'M' if i == 0 else 'L'} {x:.6f} {y:.6f}" for i, (x, y) in enumerate(stroke.points)
        )
        ET.SubElement(
            svg,
            "path",
            {
                "d": d,
                "fill": "none",
                "stroke": "#000000",
                "stroke-width": f"{stroke.width_mm:.6f}",
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            },
        )
    return ET.tostring(svg, encoding="unicode") + "\n"
