"""Forward-only page-bottom footnotes, sharing the normal centreline renderer.

Body lines are admitted only when their newly cited note heads fit. Footnote
allocations remain provisional until the page closes; no emitted body line is
moved backwards. Every note-only advance consumes at least one measured unit.
"""

from __future__ import annotations

from collections import Counter
from copy import copy
from dataclasses import dataclass, replace

from ..document.footnote_style import FootnoteStyle
from ..document.schema import Diagnostic, PageProfile, SourceSpan, digest
from ..scene.schema import LayoutSnapshot, Page, PaintOp
from .flow_regions import NoRegionProgress
from .inline import check_cancel
from .note_units import (
    NoteUnit,
    allocation_height,
    allocation_units,
    merge_table_borders,
    note_units,
    unit_cost,
)

VERSION = "page-footnotes-v3"


@dataclass(frozen=True)
class PagerCheckpoint:
    cursors: tuple
    started: tuple
    index: int
    new: tuple
    allocation: tuple
    body_bottom: float
    pages: int
    diagnostics: int

    def position(self):
        return (
            self.cursors,
            self.started,
            self.index,
            self.new,
            self.allocation,
            self.body_bottom,
            self.pages,
        )


class FootnotePager:
    """Pure trial allocations followed by page-local commits and monotone cursors."""

    def __init__(
        self, notes, reference_map, bounds, pen, cancelled=None, *, settings=None, order=None
    ):
        self.notes, self.reference_map, self.bounds = notes, reference_map, bounds
        self.pen, self.cancelled = pen, cancelled
        self.settings = settings or FootnoteStyle()
        self.order = order or {key: index for index, key in enumerate(notes)}
        self.cursors = {key: 0 for key in notes}
        self.started = []
        self.pages = []
        self.diagnostics = []
        self.index = 0
        self.new = []
        self.allocation = ()
        self.body_bottom = bounds(0)[1]
        self._cursor_state = tuple(self.cursors.items())
        self._started_state = ()

    def continuation_inputs(self):
        """Exact measured notes and reference dependencies, before body placement."""
        return (
            VERSION,
            tuple(self.notes.items()),
            tuple(self.reference_map.items()),
            self.settings,
            tuple(self.order.items()),
            self.checkpoint(),
            tuple(self.diagnostics),
        )

    def checkpoint(self):
        # Cursors/started change only at page commit. Share these frozen arrays
        # between block checkpoints instead of copying all notes for every block.
        return PagerCheckpoint(
            self._cursor_state,
            self._started_state,
            self.index,
            tuple(self.new),
            self.allocation,
            self.body_bottom,
            len(self.pages),
            len(self.diagnostics),
        )

    def restore(self, state, pages, diagnostics, *, boundary=None):
        """Restore a prefix, or splice an exactly converged suffix before finalization."""
        check_cancel(self.cancelled)
        if boundary is None:
            self.pages = list(pages[: state.pages])
            self.diagnostics = list(diagnostics[: state.diagnostics])
        else:
            self.pages.extend(pages[boundary.pages : state.pages])
            self.diagnostics.extend(diagnostics[boundary.diagnostics : state.diagnostics])
        self._cursor_state, self._started_state = state.cursors, state.started
        self.cursors, self.started = dict(state.cursors), list(state.started)
        self.index, self.new = state.index, list(state.new)
        self.allocation, self.body_bottom = state.allocation, state.body_bottom

    @property
    def pending(self):
        return [key for key in self.started if self.cursors[key] < len(self.notes[key])]

    @property
    def overhead(self):
        return self.settings.body_gap_mm + self.settings.note_gap_mm + self.pen

    def refs(self, lines):
        result = []
        for line in lines:
            for box in line:
                key = self.reference_map.get(box.run.occurrence.node_id)
                if key is not None and key not in self.started and key not in result:
                    result.append(key)
        return result

    def seed_fixed_references(self, references):
        """Reserve first-page definition heads for independently placed fields."""
        if not references:
            return
        self.new = sorted(
            {self.reference_map[n.node_id] for n in references}, key=self.order.__getitem__
        )
        required = sum(allocation_height(self.notes[key], 0, 1) for key in self.new)
        _, top, _, bottom = self.bounds(0)
        if required + self.overhead > bottom - top + 1e-9:
            self.diagnostics.append(
                Diagnostic(
                    "footnote-fixed-anchor-overflow",
                    "Fixed-field references require more note-head space than the first page supplies",
                    references[0].span,
                )
            )
        else:
            # Reserve only mandatory heads initially. The first body line can
            # then expand the band without inheriting an unnecessarily full one.
            self.allocation = tuple((key, 0, 1) for key in self.new)

    def trial(self, lines, body_bottom, *, final=False):
        check_cancel(self.cancelled)
        if normalise := getattr(self, "normalise_bottom", None):
            body_bottom = normalise(self.index, body_bottom)
        new = sorted(
            [*self.new, *(key for key in self.refs(lines) if key not in self.new)],
            key=self.order.__getitem__,
        )
        active = sorted(
            [*self.pending, *(key for key in new if key not in self.pending)],
            key=self.order.__getitem__,
        )
        if not active:
            return (), new
        _, top, _, bottom = self.bounds(self.index)
        available = bottom - body_bottom - self.overhead
        # New heads are mandatory. A continuing note also advances on a page
        # without new references, preventing starvation by a long body.
        required = {key: 1 for key in (new or active[:1])}
        # Once a preceding body line has reserved note text, later body lines
        # may not squeeze it down to a bare label. This keeps notes close to
        # their anchors instead of deferring nearly all prose to the final page.
        for key, _, count in self.allocation:
            required[key] = max(required.get(key, 0), count)
        heights = {
            key: allocation_height(self.notes[key], self.cursors[key], count)
            for key, count in required.items()
        }
        minimum = sum(heights.values())
        capacity = (
            available
            if final
            else min(
                available,
                max((bottom - top) * self.settings.page_fraction - self.overhead, minimum),
            )
        )
        if capacity + 1e-9 < minimum:
            return None
        used, result = 0, []
        for key in active:
            check_cancel(self.cancelled)
            if key in required:
                minimum -= heights[key]
            count = 0
            raw_height, allocated_height = 0, 0
            label_height = self.notes[key][self.cursors[key]].label_height
            for i in range(self.cursors[key], len(self.notes[key])):
                cost = unit_cost(self.notes[key], i, self.cursors[key])
                height = (
                    max(raw_height + cost, label_height)
                    + self.notes[key][self.cursors[key]].tail_gap_mm
                    - allocated_height
                )
                if used + height + minimum > capacity + 1e-9:
                    break
                used += height
                raw_height += cost
                allocated_height += height
                count += 1
            if count:
                result.append((key, self.cursors[key], count))
        return tuple(result), new

    def probe(self):
        return copy(self)

    def can_fit(self, lines, body_bottom):
        return self.trial(lines, body_bottom) is not None

    def accept(self, line, body_bottom):
        if normalise := getattr(self, "normalise_bottom", None):
            body_bottom = normalise(self.index, body_bottom)
        result = self.trial([line], body_bottom)
        if result is None:
            # The caller uses this only after an empty-page attempt with no
            # remaining note progress. Keep source coverage in debug output,
            # but never certify an anchor whose first note line cannot fit.
            refs = self.refs([line])
            span = line[0].run.occurrence.span if line else SourceSpan(0, 0)
            self.diagnostics.append(
                Diagnostic(
                    "footnote-anchor-overflow",
                    "Reference line and required footnote heads do not fit an empty page",
                    span,
                )
            )
            self.new.extend(key for key in refs if key not in self.new)
            self.allocation = ()
        else:
            self.allocation, self.new = result
        self.body_bottom = body_bottom

    def can_advance(self):
        return bool(self.allocation)

    def start(self, index):
        self.index, self.new = index, []
        self.body_bottom = self.bounds(index)[1]
        result = self.trial([], self.body_bottom)
        self.allocation = result[0] if result else ()

    def finish(self):
        from ..document.limits import allocating_page

        allocating_page(len(self.pages) + 1)
        self.started.extend(key for key in self.new if key not in self.started)
        self.pages.append(self.allocation)
        for key, start, count in self.allocation:
            assert start == self.cursors[key]
            self.cursors[key] += count
        self.new, self.allocation = [], ()
        self._cursor_state = tuple(self.cursors.items())
        self._started_state = tuple(self.started)

    def expand_final(self):
        result = self.trial([], self.body_bottom, final=True)
        if result is not None:
            self.allocation, self.new = result

    def drain(self):
        while self.pending:
            check_cancel(self.cancelled)
            self.start(len(self.pages))
            if getattr(self, "skip_page", lambda index: False)(self.index):
                self.finish()
                continue
            self.expand_final()
            if not self.allocation:
                # Oversized note units get a single debug placement with an
                # error. Always consume a unit rather than entering a loop.
                key = self.pending[0]
                unit = self.notes[key][self.cursors[key]]
                _, top, _, bottom = self.bounds(self.index)
                required = allocation_height(self.notes[key], self.cursors[key], 1)
                message = (
                    f"Atomic footnote table row group needs {required:.3f} mm; empty note page supplies "
                    f"{max(0, bottom - top - self.overhead):.3f} mm. Cell contents are not split across pages. "
                    "Reduce table dimensions, increase usable page height, or divide the source table while preserving merged cells."
                    if unit.table_id
                    else "Footnote line exceeds an empty page"
                )
                self.diagnostics.append(
                    Diagnostic(
                        "footnote-line-height-overflow",
                        message,
                        unit.span,
                    )
                )
                self.allocation = ((key, self.cursors[key], 1),)
            self.finish()


def _empty_page(index, template):
    if template is None:
        return Page(index, (), ())
    face = template.face(index)
    background = face.background if template.mode == "preprinted" else None
    dx = template.offset_x_mm if template.mode == "blank" else 0
    dy = template.offset_y_mm if template.mode == "blank" else 0
    rules = tuple(
        PaintOp(
            f"template:{r.name}",
            tuple((x + dx, y + dy) for x, y in r.points),
            r.width_mm,
            execution_domain="template-frame",
        )
        for r in face.rules
    )
    return Page(
        index,
        (),
        rules if template.mode == "blank" else (),
        tuple(replace(op, color="#8a8a8a") for op in rules)
        if template.mode == "preprinted" and background is None
        else (),
        background,
    )


def layout_footnotes(document, resolver, *, page, style, flow, cancelled=None, fixed_references=(), regions=None):
    from .blocks import layout_markdown

    definitions = [node for node in document.nodes if node.kind == "footnote_definition"]
    all_nodes = [n for root in document.nodes for n in root.walk()]
    refs = [n for n in all_nodes if n.kind == "footnote_reference"] + list(fixed_references)
    # Arbitrary raw HTML is outside the controlled block dialect.
    invalid = any(d.severity == "error" for d in document.diagnostics)
    body_nodes = [
        n for root in document.nodes if root.kind != "footnote_definition" for n in root.walk()
    ]
    note_nodes = [n for root in definitions for n in root.walk()]
    unsupported = next((n for n in body_nodes if n.kind == "html_block"), None)
    unsupported = unsupported or next((n for n in note_nodes if n.kind == "html_block"), None)
    invalid |= unsupported is not None
    invalid |= any(not n.children for n in definitions)
    ids = {n.node_id for n in definitions}
    invalid |= any(dict(n.attributes).get("definition_id") not in ids for n in refs)
    if invalid:
        result = layout_markdown(
            document,
            resolver,
            page=page,
            style=style,
            flow=flow,
            cancelled=cancelled,
            _footnotes=False,
            _regions=regions,
        )
        return replace(
            result,
            diagnostics=(
                *result.diagnostics,
                Diagnostic(
                    "footnote-context-pending",
                    "Footnotes require valid top-level definitions and supported content; arbitrary raw HTML is not supported",
                    unsupported.span if unsupported else refs[0].span if refs else SourceSpan(0, 0),
                ),
            ),
        )
    profile = flow.template.page if flow.template else page
    margin = profile.margin_mm
    bounds = (
        regions.note_bounds if regions else flow.template.bounds
        if flow.template or regions
        else lambda index: (margin, margin, profile.width_mm - margin, profile.height_mm - margin)
    )
    width = regions.note_width if regions else bounds(0)[2] - bounds(0)[0]
    settings = flow.footnote
    ratio = settings.text_scale
    note_style = replace(
        style,
        em_mm=style.em_mm * ratio,
        line_height_mm=style.line_height_mm * settings.line_height_scale,
    )
    note_flow = replace(
        flow,
        template=None,
        template_bindings=(),
        first_line_indent_mm=0,
        digits_follow_latin=False,
        list_indent_mm=settings.label_indent_mm,
        math=replace(flow.math, em_mm=flow.math.em_mm * ratio),
        code=replace(
            flow.code,
            em_mm=flow.code.em_mm * ratio,
            advance_mm=flow.code.advance_mm * ratio,
            line_height_mm=flow.code.line_height_mm * ratio,
        ),
    )
    notes, issues = {}, []
    if settings.separator_length_mm < style.stroke_width_mm / 2:
        issues.append(
            Diagnostic(
                "footnote-separator-size-limit",
                "Footnote separator extent is too short for the selected pen width",
                definitions[0].span,
            )
        )
    if note_style.em_mm < style.stroke_width_mm * 6:
        issues.append(
            Diagnostic(
                "footnote-text-size-limit",
                "Footnote text is too small for the selected pen width",
                definitions[0].span,
            )
        )
    for node in definitions:
        check_cancel(cancelled)
        local = replace(document, nodes=(replace(node, kind="footnote_entry"),), diagnostics=())
        from .inline import InlineRun, measure_runs

        labels, label_issues = measure_runs(
            [InlineRun(o) for o in node.occurrences], resolver, note_style, cancelled=cancelled,
            latin_spacing=flow.latin_spacing,
            punctuation_spacing=flow.punctuation_spacing,
            han_spacing=flow.han_spacing,
        )
        issues.extend(label_issues)
        entry_flow = replace(
            note_flow,
            list_indent_mm=max(settings.label_indent_mm, sum(b.advance for b in labels) + 1.5),
        )
        measure_height = max(
            1_000_000,
            (len(local.occurrences) + 1)
            * 16
            * max(
                note_style.em_mm,
                note_style.line_height_mm,
                note_flow.math.em_mm,
                note_flow.code.line_height_mm,
                *(
                    dimension
                    for table_node in node.walk()
                    if table_node.kind == "table"
                    for table_style in (flow.table_for(table_node.node_id),)
                    for dimension in (
                        table_style.line_height_mm,
                        table_style.text_em_mm,
                        table_style.digit_height_mm,
                        table_style.min_row_height_mm,
                    )
                ),
            ),
        )
        bands = []
        measured = layout_markdown(
            local,
            resolver,
            page=PageProfile(width, measure_height, 0),
            style=note_style,
            flow=entry_flow,
            cancelled=cancelled,
            _atomic_bands=bands,
        )
        issues.extend(measured.diagnostics)
        assert len(measured.pages) == 1
        labels = [f for f in measured.fragments if f.node_id == node.node_id]
        units = note_units(measured, bands, cancelled=cancelled) or (
            NoteUnit(0, note_style.line_height_mm, (), (), span=node.span),
        )
        structural_head = not labels
        if not labels:
            # Structural heads keep their own list/task markers and geometry.
            # Render the definition number through the same paragraph renderer,
            # then place it in the dedicated gutter alongside the first unit.
            label_doc = replace(
                local,
                nodes=(
                    replace(
                        local.nodes[0],
                        children=(replace(node, kind="paragraph", children=(), occurrences=()),),
                    ),
                ),
            )
            label_snapshot = layout_markdown(
                label_doc,
                resolver,
                page=PageProfile(width, measure_height, 0),
                style=note_style,
                flow=entry_flow,
                cancelled=cancelled,
                _references_only=True,
            )
            issues.extend(label_snapshot.diagnostics)
            label_page = label_snapshot.pages[0]
            dy = units[0].top - min(f.logical_bounds[1] for f in label_page.fragments)

            def shift(bounds, dy=dy):
                return (bounds[0], bounds[1] + dy, bounds[2], bounds[3] + dy) if bounds else None

            labels = [
                replace(
                    f,
                    baseline_mm=f.baseline_mm + dy,
                    logical_bounds=shift(f.logical_bounds),
                    ink_bounds=shift(f.ink_bounds),
                )
                for f in label_page.fragments
            ]
            label_ops = tuple(
                replace(op, points=tuple((x, y + dy) for x, y in op.points))
                for op in label_page.paint_ops
            )
            units = (
                replace(
                    units[0],
                    fragments=(*labels, *units[0].fragments),
                    ops=(*label_ops, *units[0].ops),
                ),
                *units[1:],
            )
        label_height = max(f.logical_bounds[3] for f in labels) - min(
            f.logical_bounds[1] for f in labels
        )
        notes[node.node_id] = tuple(
            replace(
                unit,
                label_height=label_height,
                tail_gap_mm=note_style.line_height_mm * 0.25 if structural_head else 0,
            )
            for unit in units
        )
    pager = FootnotePager(
        notes,
        {n.node_id: dict(n.attributes)["definition_id"] for n in refs},
        bounds,
        style.stroke_width_mm,
        cancelled,
        settings=settings,
        order={n.node_id: int(dict(n.attributes)["number"]) for n in definitions},
    )
    pager.seed_fixed_references(fixed_references)
    if regions:
        pager.normalise_bottom=regions.note_bottom
        pager.skip_page=lambda index:not regions.template.layout(index).body_frames
    body = replace(
        document, nodes=tuple(n for n in document.nodes if n.kind != "footnote_definition")
    )
    stopped = None
    try:
        result = layout_markdown(
            body, resolver, page=profile, style=style, flow=flow, cancelled=cancelled, _footnotes=pager,
            _regions=regions
        )
    except NoRegionProgress as error:
        if not error.pages:
            raise
        stopped = error
        # Close allocations for body that was actually placed. Definitions after
        # the blocked object do not become orphan note-only pages in this preview.
        pager.expand_final()
        pager.finish()
        key = digest([document.content_key, "stopped-body", error.span.start])
        result = LayoutSnapshot(key, key, document.document_id, document.revision, profile,
                                error.pages, error.diagnostics, resolver.resource_key, "stopped-body")
    for node in definitions if stopped is None else ():
        if node.node_id not in pager.started:
            # Unsupported inline containers may preserve a reference in the AST
            # without producing its box. Keep definitions in debug output and
            # report the missing anchor rather than crashing the coverage audit.
            pager.diagnostics.append(
                Diagnostic(
                    "footnote-anchor-unplaced",
                    "Footnote reference could not be placed in a supported body container",
                    node.span,
                )
            )
            pager.started.append(node.node_id)
    pager.drain()
    from ..document.limits import BudgetedOps, PointAccumulator

    pages = list(result.pages)
    while len(pages) < len(pager.pages):
        pages.append(_empty_page(len(pages), flow.template))
    point_meter = PointAccumulator(pages)
    for index, allocation in enumerate(pager.pages):
        if not allocation:
            continue
        left, _top, right, bottom = bounds(index)
        height = sum(
            allocation_height(notes[key], start, count) for key, start, count in allocation
        )
        y = bottom - height
        separator_y = y - settings.note_gap_mm - style.stroke_width_mm / 2
        fragments = list(pages[index].fragments)
        ops = BudgetedOps(point_meter, pages[index].paint_ops)
        images = list(pages[index].images)
        ops.append(
            PaintOp(
                f"footnotes:separator:{index}",
                (
                    (left + style.stroke_width_mm / 2, separator_y),
                    (
                        left
                        + min(
                            max(settings.separator_length_mm, style.stroke_width_mm / 2),
                            right - left - style.stroke_width_mm / 2,
                        ),
                        separator_y,
                    ),
                ),
                style.stroke_width_mm,
                execution_domain="page-footnotes",
            )
        )
        for key, start, count in allocation:
            allocation_top = y
            if start:
                # Repeat only the number on continuation pages; its source and
                # chosen asset remain the original definition marker.
                labels = [f for f in notes[key][0].fragments if f.node_id == key]
                label_ids = {f.occurrence_id for f in labels}
                first_unit = notes[key][start].continuation or notes[key][start]
                target_baseline = (
                    first_unit.fragments[0].baseline_mm + y - first_unit.top
                    if first_unit.fragments
                    and not first_unit.fragments[0].status.startswith("image-")
                    else y + labels[0].baseline_mm - notes[key][0].top
                )
                min_baseline = y + max(f.baseline_mm - f.logical_bounds[1] for f in labels)
                max_baseline = (
                    y
                    + max(first_unit.height, notes[key][start].label_height)
                    - max(f.logical_bounds[3] - f.baseline_mm for f in labels)
                )
                target_baseline = max(min_baseline, min(target_baseline, max_baseline))
                dy_label = target_baseline - labels[0].baseline_mm
                for f in labels:
                    shift = lambda b, dx=left, dy=dy_label: (
                        b[0] + dx,
                        b[1] + dy,
                        b[2] + dx,
                        b[3] + dy,
                    )
                    fragments.append(
                        replace(
                            f,
                            fragment_id=digest([f.occurrence_id, index, VERSION, "continued"]),
                            page_index=index,
                            x_mm=f.x_mm + left,
                            baseline_mm=f.baseline_mm + dy_label,
                            logical_bounds=shift(f.logical_bounds),
                            ink_bounds=shift(f.ink_bounds) if f.ink_bounds else None,
                            repeated=True,
                            container_id=f"footnote:{key}",
                        )
                    )
                ops.extend(
                    replace(
                        op,
                        points=tuple((x + left, yy + dy_label) for x, yy in op.points),
                        execution_domain="page-footnotes",
                    )
                    for op in notes[key][0].ops
                    if op.occurrence_id in label_ids
                )
            for unit, repeated_header, overlap in allocation_units(notes[key], start, count):
                y -= overlap
                dy = y - unit.top
                for f in unit.fragments:
                    shift = lambda b, dx=left, dy=dy: (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)
                    fragments.append(
                        replace(
                            f,
                            fragment_id=digest([f.occurrence_id, index, VERSION, "table-header"])
                            if repeated_header
                            else digest([f.occurrence_id, index, VERSION]),
                            repeated=f.repeated or repeated_header,
                            page_index=index,
                            x_mm=f.x_mm + left,
                            baseline_mm=f.baseline_mm + dy,
                            logical_bounds=shift(f.logical_bounds),
                            ink_bounds=shift(f.ink_bounds) if f.ink_bounds else None,
                            container_id=f"footnote:{key}",
                        )
                    )
                ops.extend(
                    replace(
                        op,
                        points=tuple((x + left, yy + dy) for x, yy in op.points),
                        execution_domain="page-footnotes",
                    )
                    for op in unit.ops
                )
                images.extend(
                    replace(
                        image,
                        bounds=(
                            image.bounds[0] + left,
                            image.bounds[1] + dy,
                            image.bounds[2] + left,
                            image.bounds[3] + dy,
                        ),
                    )
                    for image in unit.images
                )
                y += unit.height
            y = (
                max(y, allocation_top + notes[key][start].label_height)
                + notes[key][start].tail_gap_mm
            )
        pages[index] = replace(
            pages[index],
            fragments=tuple(fragments),
            paint_ops=merge_table_borders(ops),
            images=tuple(images),
        )
    expected = Counter(f.occurrence_id for f in result.fragments if not f.repeated)
    expected.update(
        f.occurrence_id for key, units in notes.items() if stopped is None or key in pager.started
        for unit in units for f in unit.fragments
    )
    actual = Counter(f.occurrence_id for p in pages for f in p.fragments if not f.repeated)
    if expected != actual:
        raise RuntimeError("Footnote pagination lost or duplicated source instances")
    key = digest(
        {
            "body": result.job_key,
            "version": VERSION,
            "flow": flow.layout_record(),
            "source": document.content_key,
            "selections": resolver.selection_records(),
        }
    )
    finished = replace(
        result,
        snapshot_id=key,
        job_key=key,
        pages=tuple(pages),
        layout_version=result.layout_version + "/" + VERSION,
        diagnostics=(*result.diagnostics, *issues, *pager.diagnostics),
    )
    if stopped is not None:
        stopped.pages, stopped.diagnostics = finished.pages, finished.diagnostics
        raise stopped
    return finished
