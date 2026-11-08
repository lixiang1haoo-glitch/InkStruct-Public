"""Bounded, frozen page context for optical adjustment; no re-layout or selection."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextGlyph:
    fragment: object
    glyph: object
    strokes: tuple
    variation: object = None

    def original(self):
        f, g = self.fragment, self.glyph
        if not g:
            return self.strokes
        x0 = f.x_mm + f.glyph_origin_offset_mm
        top = f.baseline_mm - g.metrics.baseline * f.glyph_em_mm
        strokes = tuple(tuple((x0 + x * f.glyph_em_mm, top + y * f.glyph_em_mm)
                              for x, y in stroke) for stroke in g.strokes)
        if self.variation:
            from ..layout.han_variation import varied_strokes
            strokes = varied_strokes(strokes, f.occurrence_id, self.variation)
        return strokes

    def corrected(self, rule):
        f = self.fragment
        x0 = f.x_mm + f.glyph_origin_offset_mm
        return tuple(tuple((x0 + (x - x0) * rule.scale_x + rule.dx_em * f.glyph_em_mm,
                            f.baseline_mm + (y - f.baseline_mm) * rule.scale_y
                            + rule.dy_em * f.glyph_em_mm) for x, y in stroke)
                     for stroke in self.original())


def surrounding_glyphs(snapshot, selected, asset_for_fragment, *, flow=None, document=None):
    """At most three neighbours each side, from this physical row and frame.

    Keep current page operations for neighbours, including applied corrections;
    do not resolve new samples. Spatial filtering handles repeated table heads.
    """
    eligible = set()
    if flow is not None and flow.han_variation.enabled and document is not None:
        from ..layout.han_variation import eligible_occurrences
        eligible = eligible_occurrences(document)
    page = snapshot.pages[selected.page_index]
    em = selected.glyph_em_mm or 6
    row = sorted((f for f in page.fragments
                  if f.line_index == selected.line_index and f.container_id == selected.container_id
                  and abs(f.baseline_mm - selected.baseline_mm) < em * .25
                  and abs(f.x_mm - selected.x_mm) <= em * 6), key=lambda f: f.x_mm)
    index = next((i for i, f in enumerate(row) if f.fragment_id == selected.fragment_id), None)
    if index is None:
        row, index = [selected], 0
    row = row[max(0, index - 3):index + 4]
    wanted = {f.occurrence_id for f in row}
    ops = {}
    for op in page.paint_ops:
        if op.occurrence_id in wanted:
            ops.setdefault(op.occurrence_id, []).append(op)
    result = []
    for f in row:
        bounds = f.ink_bounds
        strokes = tuple(op.points for op in ops.get(f.occurrence_id, ()) if bounds and all(
            bounds[0] - 1e-8 <= x <= bounds[2] + 1e-8
            and bounds[1] - 1e-8 <= y <= bounds[3] + 1e-8 for x, y in op.points))
        result.append(ContextGlyph(f, asset_for_fragment(f) if f.asset_id else None, strokes,
                                   flow.han_variation if f.occurrence_id in eligible else None))
    return tuple(result)
