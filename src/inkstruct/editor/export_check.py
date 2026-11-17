"""Check the selected pages against the intended output, using frozen geometry."""
from dataclasses import dataclass, replace

from ..plotter.adapters import can_export_with_image_omission, reference_image_export_scope
from ..plotter.options import prepare_export
from ..renderers.pages import png_dimensions
from ..scene.schema import Page


def selected_snapshot(snapshot, indices):
    selected = set(indices)
    if len(selected) == len(snapshot.pages):
        return snapshot
    # Retain the original indices for the plotter's contiguous plan contract.
    placed = [tuple(f.span for f in page.fragments) + tuple(i.span for i in page.images)
              for page in snapshot.pages]

    def in_scope(diagnostic):
        span = diagnostic.span
        if span.start >= span.end or diagnostic.code.startswith("template-"):
            return True
        pages = [i for i, spans in enumerate(placed)
                 if any(s.start < span.end and span.start < s.end for s in spans)]
        # Unplaced or truncated content cannot safely be attributed to one page.
        return not pages or any(i in selected for i in pages)

    return replace(snapshot, pages=tuple(p if p.index in selected else Page(p.index, (), ())
                                         for p in snapshot.pages),
                   diagnostics=tuple(d for d in snapshot.diagnostics if in_scope(d)))


@dataclass(frozen=True)
class MachineOutput:
    plan: object
    scope: dict
    pages: tuple[int, ...]


@dataclass(frozen=True)
class ExportCheck:
    snapshot: object
    pages: tuple[int, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    images: tuple
    machine: MachineOutput | None
    partial: MachineOutput | None


def _machine(snapshot, document, flow, options):
    plan, scope = prepare_export(snapshot, document, flow, options)
    pages = tuple(i for i in options.pages
                  if any(s.execution_domain != 'registration' for s in plan.pages[i].strokes))
    scope['actual_page_numbers'] = [i + 1 for i in pages]
    scope['skipped_empty_pages'] = [i + 1 for i in options.pages if i not in pages]
    return MachineOutput(plan, scope, pages) if pages else None


def check_export(snapshot, document, flow, options, *, machine, png=False):
    scoped = selected_snapshot(snapshot, options.pages)
    image_scope = reference_image_export_scope(scoped)
    images = tuple(image_scope['omitted_images']) if image_scope else ()
    warnings = tuple(d.message for d in scoped.diagnostics if d.severity != 'error')
    missing = {i.span for p in scoped.pages for i in p.images if i.png_base64 is None}
    can_omit = machine and can_export_with_image_omission(scoped)
    errors = tuple(d.message for d in scoped.diagnostics if d.severity == 'error' and not (
        can_omit and d.code in {'image-resource-missing', 'image-import-missing'} and d.span in missing))
    if png:
        try:
            png_dimensions(scoped.page_profile, 144)
        except ValueError:
            errors += ('纸张尺寸超过 PNG 像素限制，请改用页面 SVG 或整篇 PDF。',)
    normal = partial = None
    if machine and not errors:
        try:
            normal = _machine(scoped, document, flow, options)
        except ValueError as error:
            errors = (str(error),)
    if errors:
        try:
            partial = _machine(scoped, document, flow, replace(options, force=True))
        except ValueError:
            # Invalid calibration or a failed table filter also prevents partial output.
            pass
    if machine and not errors and normal is None:
        errors = ('所选页没有可写笔迹',)
    elif machine and errors and partial is None and not any(
            p.paint_ops for p in scoped.pages):
        errors = ('所选页没有可写笔迹', *errors)
    return ExportCheck(scoped, options.pages, errors, warnings, images, normal, partial)
