"""Geometry-only v3 reference SVG, never a machine-export substitute."""

from html import escape


def geometry_preview(template, layout_id):
    p = next((p for p in template.effective_layouts if p.layout_id == layout_id), None)
    if p is None:
        raise ValueError("Unknown template layout")
    w, h = template.width_mm, template.height_mm
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">',
        "<title>Template design reference — not machine output</title>",
        f'<rect width="{w}" height="{h}" fill="white" stroke="#94a3b8" stroke-width="0.5"/>',
    ]
    if p.background:
        lines.append(
            f'<image width="{w}" height="{h}" preserveAspectRatio="none" xlink:href="data:image/png;base64,{p.background.png_base64}"/>'
        )
    lines.append(f'<g transform="translate({template.offset_x_mm} {template.offset_y_mm})">')
    for r in p.rules:
        points = " ".join(f"{x},{y}" for x, y in r.points)
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="#64748b" stroke-width="{r.width_mm}"/>'
        )
    for f in p.frames:
        r = f.region
        label = (
            f"{f.order}. 正文"
            if f.role == "body"
            else "字段 " + f.field_id
            if f.role == "field"
            else "页码"
        )
        lines.extend(
            [
                f'<rect x="{r.x_mm}" y="{r.y_mm}" width="{r.width_mm}" height="{r.height_mm}" fill="#2563eb" fill-opacity="0.06" stroke="#2563eb" stroke-width="0.3"/>',
                f'<text x="{r.x_mm + 1}" y="{r.y_mm + 4}" font-size="3">{escape(label + " · " + f.label)}</text>',
            ]
        )
        if f.paper_grid:
            for baseline in f.paper_grid.baselines():
                y = r.y_mm + baseline
                lines.append(
                    f'<path d="M {r.x_mm} {y} h {r.width_mm}" fill="none" stroke="#0284c7" '
                    'stroke-width="0.3" stroke-dasharray="1.4 0.8"/>'
                )
    lines.append("</g></svg>")
    return "\n".join(lines)
