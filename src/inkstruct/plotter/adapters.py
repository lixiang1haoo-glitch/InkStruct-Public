from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from urllib.parse import unquote

from ..document.images import local_raster_reference_name
from ..document.limits import validate_snapshot
from ..scene.schema import LayoutSnapshot, PaintOp
from .schema import PlotPage, PlotPlan, PlotStroke


def _image_omission(page, image):
    loaded = image.png_base64 is not None and image.original_sha256 is not None
    missing = image.png_base64 is None and image.original_sha256 is None
    name = local_raster_reference_name(image.source)
    if not loaded and not (missing and name):
        return None
    return {'page_index': page.index, 'page_number': page.index + 1,
            'occurrence_id': image.occurrence_id, 'node_id': image.node_id, 'span': asdict(image.span),
            'source': image.source, 'display_name': name or unquote(image.source),
            'original_sha256': image.original_sha256, 'bounds': image.bounds,
            'reason': 'loaded-raster' if loaded else 'resource-not-loaded'}


def can_export_with_image_omission(snapshot: LayoutSnapshot) -> bool:
    """A separate export capability; full-document errors remain untouched."""
    missing_spans = set()
    for page in snapshot.pages:
        for image in page.images:
            item = _image_omission(page, image)
            if item is None:
                return False
            if item['reason'] == 'resource-not-loaded':
                missing_spans.add(image.span)
    return all(d.severity != 'error' or (
        d.code in {'image-resource-missing', 'image-import-missing'} and d.span in missing_spans
    ) for d in snapshot.diagnostics)


def reference_image_export_scope(snapshot: LayoutSnapshot) -> dict | None:
    """Describe intentional omissions without editing layout or source resources."""
    images = [item for page in snapshot.pages for image in page.images
              if (item := _image_omission(page, image)) is not None]
    if not images:
        return None
    return {
        'kind': 'document-with-reference-images-omitted',
        'image_policy': 'omit-raster-preserve-layout-and-captions',
        'omitted_images': images,
    }


def plan_from_snapshot(snapshot: LayoutSnapshot, *, omit_reference_images: bool = False) -> PlotPlan:
    """Adapt centreline PaintOps only. Preview decorations never become ink.

    Single points are deliberately blocked until a calibrated nonzero dot adapter
    is selected. The source asset, pressure and timestamps remain untouched.
    """
    validate_snapshot(snapshot)
    omission_ready = omit_reference_images and can_export_with_image_omission(snapshot)
    if not snapshot.exportable and not omission_ready:
        raise ValueError("Unresolved document errors block plotter export")
    if not snapshot.plotter_exportable and not omission_ready:
        raise ValueError("Raster image references cannot be exported to the plotter")
    pages = []
    for page in snapshot.pages:
        strokes = []
        counters = Counter()
        assets = {f.occurrence_id: f.asset_id or f.source_resource_id for f in page.fragments}
        for op in page.paint_ops:
            if type(op) is not PaintOp:
                raise ValueError(f"Unsupported plotter operation: {type(op).__name__}")
            # The current renderer's default dark ink is a single black pen.
            if op.color.lower() not in {"#111827", "#000000", "#000", "black"}:
                raise ValueError(f"{op.occurrence_id}: multi-pen colour is not configured")
            ordinal = counters[op.occurrence_id]
            counters[op.occurrence_id] += 1
            asset = assets.get(op.occurrence_id)
            strokes.append(
                PlotStroke(
                    stroke_id=f"page:{page.index}:{op.occurrence_id}:stroke:{ordinal}",
                    points=op.points,
                    width_mm=op.width_mm,
                    occurrence_id=op.occurrence_id,
                    source_stroke_id=f"{asset}:stroke:{ordinal}" if asset else None,
                    execution_domain=op.execution_domain,
                )
            )
        pages.append(
            PlotPage(
                page.index,
                snapshot.page_profile.width_mm,
                snapshot.page_profile.height_mm,
                tuple(strokes),
            )
        )
    return PlotPlan(snapshot.document_id, snapshot.snapshot_id, tuple(pages))
