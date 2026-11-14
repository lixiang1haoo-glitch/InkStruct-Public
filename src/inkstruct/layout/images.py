"""Atomic raster figure and handwritten alt-caption measurement."""

from dataclasses import dataclass, replace

from ..document.image_labels import ImageLabel
from ..document.line_svg import LineSvgResource
from ..document.schema import Diagnostic
from .inline import break_lines, inline_runs, measure_runs
from .plain import CLOSING, OPENING


@dataclass(frozen=True)
class MeasuredImageLabel:
    node_id: str
    x: float
    baseline: float
    boxes: tuple


@dataclass(frozen=True)
class MeasuredImage:
    resource: object
    width: float
    height: float
    lines: tuple
    metrics: tuple
    gap: float
    total_height: float
    alignment: str
    diagnostics: tuple
    paths: tuple = ()
    labels: tuple[MeasuredImageLabel, ...] = ()


def measure_labels(node, resolver, style, flow, width, height, cancelled):
    labels, diagnostics = [], []
    for label in node.children:
        if label.kind != "image_label" or not label.children:
            continue
        settings = ImageLabel.from_node(label)
        em = settings.em_mm or style.em_mm
        boxes, issues = measure_runs(
            tuple(run for child in label.children for run in inline_runs(child)),
            resolver, replace(style, em_mm=em), cancelled=cancelled,
            math_style=flow.math if settings.em_mm is None else replace(flow.math, em_mm=em),
            latin_spacing=flow.latin_spacing, punctuation_spacing=flow.punctuation_spacing,
            han_spacing=flow.han_spacing,
            han_variation=flow.han_variation,
        )
        diagnostics.extend(issues)
        if not boxes:
            continue
        label_width = sum(box.advance for box in boxes)
        ascent = max(box.ascent for box in boxes)
        descent = max(box.descent for box in boxes)
        x = width * settings.x / 100 - label_width / 2
        baseline = height * settings.y / 100 + (ascent - descent) / 2
        if x < -1e-9 or x + label_width > width + 1e-9 or baseline - ascent < -1e-9 or baseline + descent > height + 1e-9:
            diagnostics.append(Diagnostic("image-label-overflow", "图片标注超出图片边缘，可移动标注或减小字号。",
                                          label.span, "warning"))
        labels.append(MeasuredImageLabel(label.node_id, x, baseline, tuple(boxes)))
    return tuple(labels), diagnostics


def measure_image(block, resolver, style, flow, width, cancelled):
    image_style = flow.image_for(block.node.node_id)
    source = dict(block.node.attributes).get("src", "")
    resource = next((r for r in flow.images if r.source == source), None)
    iw, ih = image_style.dimensions(resource)
    boxes, issues = measure_runs(
        block.runs,
        resolver,
        style,
        cancelled=cancelled,
        math_style=flow.math,
        footnote_style=flow.footnote,
        latin_spacing=flow.latin_spacing,
        punctuation_spacing=flow.punctuation_spacing,
        han_spacing=flow.han_spacing,
        han_variation=flow.han_variation,
    )
    lines = break_lines(boxes, iw, cancelled=cancelled) if boxes else []
    metrics = []
    radius = style.stroke_width_mm / 2
    for line in lines:
        visible = [b for b in line if b.status not in {"space", "line-break"}]
        if visible and (
            visible[0].run.occurrence.text in CLOSING or visible[-1].run.occurrence.text in OPENING
        ):
            issues.append(
                Diagnostic(
                    "image-caption-forbidden-boundary",
                    "Caption has a forbidden punctuation line boundary",
                    block.node.span,
                )
            )
        ascent = max([0.88 * style.em_mm + radius] + [b.ascent for b in line])
        descent = max([0.12 * style.em_mm + radius] + [b.descent for b in line])
        metrics.append((ascent, descent, max(style.line_height_mm, ascent + descent)))
        if sum(b.advance for b in line) > iw + 1e-9:
            issues.append(
                Diagnostic(
                    "image-caption-width-overflow",
                    "Image caption exceeds figure width",
                    block.node.span,
                )
            )
    if iw > width + 1e-9:
        issues.append(
            Diagnostic(
                "image-width-overflow",
                "Image exceeds content width; adjust image dimensions",
                block.node.span,
            )
        )
    paths = ()
    if isinstance(resource, LineSvgResource):
        try:
            paths = resource.paths(iw, ih, image_style.svg_tolerance_mm)
            # Guard the full pen footprint plus curve approximation near the figure boundary.
            guard = radius + image_style.svg_tolerance_mm
            if any(
                x < guard or y < guard or x > iw - guard or y > ih - guard
                for path in paths
                for x, y in path
            ):
                issues.append(
                    Diagnostic(
                        "svg-ink-overflow",
                        "SVG ink approaches figure edge; add padding inside its viewBox",
                        block.node.span,
                    )
                )
            issues.append(
                Diagnostic(
                    "svg-centreline-pen",
                    f"Single-line SVG uses document pen; final-size tolerance {image_style.svg_tolerance_mm:g} mm",
                    block.node.span,
                    "warning",
                )
            )
        except ValueError as error:
            issues.append(Diagnostic("svg-compile-failed", str(error), block.node.span))
    elif resource is None:
        issues.append(
            Diagnostic(
                "image-resource-missing",
                f"Image resource is not embedded: {source}",
                block.node.span,
            )
        )
    else:
        issues.append(
            Diagnostic(
                "image-reference-only",
                "Raster reference image will be omitted from machine SVG after confirmation; layout and caption are preserved",
                block.node.span,
                "warning",
            )
        )
    labels, label_issues = measure_labels(block.node, resolver, style, flow, iw, ih, cancelled)
    issues.extend(label_issues)
    gap = image_style.caption_gap_mm if lines else 0
    return MeasuredImage(
        resource,
        iw,
        ih,
        tuple(lines),
        tuple(metrics),
        gap,
        ih + gap + sum(m[2] for m in metrics),
        image_style.align,
        tuple(issues),
        paths,
        labels,
    )
