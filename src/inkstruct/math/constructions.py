"""Pen-aware array tracks and accent polylines, independent of glyph resolution."""


def array_geometry(node, rows, *, em, style, pen, measure=None):
    attributes = dict(node.attributes)
    columns = attributes["columns"]
    nr, nc = len(rows), len(columns)
    vertical, horizontal = [[] for _ in range(nc + 1)], [[] for _ in range(nr + 1)]
    for child in node.children:
        if child.kind == "ArrayRule":
            attrs = dict(child.attributes)
            (vertical if attrs["axis"] == "vertical" else horizontal)[
                int(attrs["boundary"])
            ].append(child)
    widths = [max(0.5 * em, *(row[c].width for row in rows)) for c in range(nc)]
    ascents = [max(0.88 * em + pen / 2, *(cell.ascent for cell in row)) for row in rows]
    descents = [max(0.25 * em + pen / 2, *(cell.descent for cell in row)) for row in rows]
    clearance = max(style.array_rule_clearance_em * em, 1.5 * pen)
    separation = max(0.15 * em, 2 * pen)

    def tracks(groups, base):
        gaps, centers = [], []
        for i, group in enumerate(groups):
            count = len(group)
            if group and dict(group[0].attributes).get("style") == "cline":
                count = 1
            gap = base / 2 if i in {0, len(groups) - 1} else base
            if count:
                gap = max(gap, pen + (count - 1) * separation + 2 * clearance)
            gaps.append(gap)
            centers.append([gap / 2 + (j - (count - 1) / 2) * separation for j in range(count)])
        return gaps, centers

    xgaps, vx = tracks(vertical, max(style.matrix_col_gap_em * em, 2 * pen))
    ygaps, hy = tracks(horizontal, max(style.matrix_row_gap_em * em, 2 * pen))
    width, height = sum(widths) + sum(xgaps), sum(ascents) + sum(descents) + sum(ygaps)
    baselines, y = [], 0
    for r in range(nr):
        hy[r] = [y + v for v in hy[r]]
        y += ygaps[r]
        baselines.append(y + ascents[r])
        y += ascents[r] + descents[r]
    hy[-1] = [y + v for v in hy[-1]]
    top = (
        -baselines[0]
        if attributes["position"] == "t"
        else -baselines[-1]
        if attributes["position"] == "b"
        else -style.axis_em * em - height / 2
    )
    xs, boundaries, x = [], [], 0
    for c in range(nc):
        boundaries.append(x + xgaps[c] / 2)
        vx[c] = [x + v for v in vx[c]]
        x += xgaps[c]
        xs.append(x)
        x += widths[c]
    boundaries.append(x + xgaps[-1] / 2)
    vx[-1] = [x + v for v in vx[-1]]
    placements = []
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            offset = (widths[c] - cell.width) * {"l": 0, "c": 0.5, "r": 1}[columns[c]]
            placements.append((cell, xs[c] + offset, top + baselines[r]))
    left, right = (vx[0][0] if vx[0] else pen / 2), (vx[-1][-1] if vx[-1] else width - pen / 2)
    # Partial clines do not shorten unrelated vertical rules at outer boundaries.
    upper = (
        hy[0][0]
        if horizontal[0] and dict(horizontal[0][0].attributes)["style"] == "hline"
        else pen / 2
    )
    lower = (
        hy[-1][-1]
        if horizontal[-1] and dict(horizontal[-1][0].attributes)["style"] == "hline"
        else height - pen / 2
    )
    rules = []
    if measure:
        if nc > 1:
            edge = xs[0] + widths[0]
            measure("matrix_col_gap_em", (edge, top), (xs[1], top), "数组列槽")
        if nr > 1:
            edge = top + baselines[0] + descents[0]
            measure("matrix_row_gap_em", (width, edge), (width, edge + ygaps[1]), "数组行槽")
        for c, centers in enumerate(vx):
            if centers:
                if c < nc:
                    a, b = centers[-1] + pen / 2, xs[c]
                else:
                    a, b = xs[-1] + widths[-1], centers[0] - pen / 2
                measure("array_rule_clearance_em", (a, top), (b, top), "线至列框")
                break
        for r, centers in enumerate(hy):
            if centers:
                if r < nr:
                    a, b = top + centers[-1] + pen / 2, top + baselines[r] - ascents[r]
                else:
                    a, b = top + baselines[-1] + descents[-1], top + centers[0] - pen / 2
                measure("array_rule_clearance_em", (width, a), (width, b), "线至行框")
                break
    for c, group in enumerate(vertical):
        for source, x in zip(group, vx[c]):
            rules.append((source, "array-vertical", ((x, top + upper), (x, top + lower))))
    for r, group in enumerate(horizontal):
        for i, source in enumerate(group):
            attrs = dict(source.attributes)
            first, last = int(attrs["first"]), int(attrs["last"])
            a, b = (
                left if first == 0 else boundaries[first],
                right if last == nc else boundaries[last],
            )
            y = top + hy[r][i if attrs["style"] == "hline" else 0]
            rules.append((source, "array-horizontal", ((a, y), (b, y))))
    return placements, rules, width, top, height


def accent_geometry(name, content, *, em, style, pen):
    clearance = max(style.accent_clearance_em * em, 1.5 * pen)
    height = max(style.accent_height_em * em, 1.5 * pen)
    wide = name in {
        "overline",
        "underline",
        "widehat",
        "widetilde",
        "overrightarrow",
        "overleftarrow",
        "overleftrightarrow",
    }
    span = max(pen, content.width - pen) if wide else max(pen, min(0.65 * em, content.width - pen))
    if name in {"vec", "overrightarrow", "overleftarrow", "overleftrightarrow"}:
        head = max(height, 1.5 * pen)
        span = max(span, 2 * head + pen)
        paths = [((0, height / 2), (span, height / 2))]
        if name != "overleftarrow":
            paths.append(((span - head, 0), (span, height / 2), (span - head, height)))
        if name in {"overleftarrow", "overleftrightarrow"}:
            paths.append(((head, 0), (0, height / 2), (head, height)))
    elif name in {"hat", "widehat"}:
        span = max(span, 2 * pen)
        paths = [((0, height), (span / 2, 0), (span, height))]
    elif name in {"tilde", "widetilde"}:
        span = max(span, 4 * pen)
        paths = [((0, height / 2), (span / 4, 0), (span * 3 / 4, height), (span, height / 2))]
    elif name in {"dot", "ddot"}:
        height = 0
        span = pen if name == "dot" else 4 * pen
        paths = [((0, 0), (pen, 0))]
        if name == "ddot":
            paths.append(((3 * pen, 0), (4 * pen, 0)))
    else:
        height = 0
        paths = [((0, 0), (span, 0))]
    width = max(content.width, span + pen)
    x = (width - span) / 2
    y = (
        content.descent + clearance + pen / 2
        if name == "underline"
        else -content.ascent - clearance - pen / 2 - height
    )
    paths = [tuple((px + x, py + y) for px, py in pts) for pts in paths]
    return (content, (width - content.width) / 2, 0), paths, width
