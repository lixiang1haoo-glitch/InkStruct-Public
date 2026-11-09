"""Exact-input pagination checkpoints, scoped to one editor build worker.

Measurements are still performed for the whole document. Validated prefix and
converged suffix placement can be reused, including template body geometry.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace

from ..cache import BoundedCache
from ..document.cancellation import check_cancel
from ..document.limits import policy_key
from ..document.schema import digest
from .measurement_cache import _freeze, _weight

VERSION = "footnote-pagination-v4"
_active = ContextVar("inkstruct_continuation", default=None)


class ContinuationCache(BoundedCache):
    def __init__(self, *, max_weight=192 * 1024**2):
        super().__init__(max_entries=1, max_weight=max_weight)
        self.enabled = True
        self.suffix_enabled = True  # Internal baseline/debug switch, not a document setting.
        self.reused_blocks = self.placed_blocks = self.reused_pages = 0
        self.reused_prefix_blocks = self.reused_suffix_blocks = 0

    def record(self, prefix, suffix, placed, pages):
        with self._lock:
            self.reused_blocks += prefix + suffix
            self.reused_prefix_blocks += prefix
            self.reused_suffix_blocks += suffix
            self.placed_blocks += placed
            self.reused_pages += pages

    def statistics(self):
        with self._lock:
            return dict(
                super().statistics(),
                reused_blocks=self.reused_blocks,
                placed_blocks=self.placed_blocks,
                reused_pages=self.reused_pages,
                reused_prefix_blocks=self.reused_prefix_blocks,
                reused_suffix_blocks=self.reused_suffix_blocks,
            )


@contextmanager
def continuation_scope(cache):
    token = _active.set(cache if cache is not None and cache.enabled else None)
    try:
        yield
    finally:
        _active.reset(token)


@dataclass(frozen=True)
class Checkpoint:
    page: int
    fragments: int
    ops: int
    images: int
    y: float
    line_index: int
    previous_heading_page: int | None
    diagnostics: int
    footnotes: object = None

    def position(self):
        # Buffer counts may differ after an edit. Geometry and generated IDs
        # depend on the page, vertical position and global line index instead.
        return (
            self.page,
            self.y,
            self.line_index,
            self.previous_heading_page,
            self.footnotes.position() if self.footnotes is not None else None,
        )


@dataclass(frozen=True)
class Continuation:
    inputs: tuple
    checkpoints: tuple[Checkpoint, ...]
    pages: tuple
    diagnostics: tuple
    input_weights: tuple[int, ...]
    resources: tuple
    resource_weight: int
    finished_pages: tuple
    coordination: tuple
    note_pages: tuple
    note_diagnostics: tuple


@dataclass(frozen=True)
class Prepared:
    cache: ContinuationCache
    key: tuple
    inputs: tuple
    previous: Continuation | None
    common: int
    resources: tuple
    suffix: int
    coordination: tuple


def prepare(
    document, resolver, page, style, flow, measured, tables, images, codes, cancelled, *, pager=None
):
    cache = _active.get()
    if cache is None:
        return None
    from ..assets.resolver import SELECTION_VERSION
    from ..math.handwritten import MATH_LAYOUT_VERSION
    from .blocks import LAYOUT_VERSION

    key = (
        VERSION,
        LAYOUT_VERSION,
        MATH_LAYOUT_VERSION,
        SELECTION_VERSION,
        policy_key(),
        document.document_id,
        digest({"page": asdict(page), "style": asdict(style), "flow": asdict(flow)}),
    )
    # Full measured inputs include exact source offsets, identities, current
    # selected glyph geometry/metrics/provenance, tables, images and code wraps.
    # Re-measuring also replays resolver selection side effects on every request.
    inputs = []
    for item in measured:
        check_cancel(cancelled)
        node_id = item[0].node.node_id
        inputs.append(_freeze((item, tables.get(node_id), images.get(node_id), codes.get(node_id))))
    inputs = tuple(inputs)
    resources = tuple(g for pool in resolver.pools.values() for g in pool)
    previous = cache.get(key)
    coordination = pager.continuation_inputs() if pager else ()
    # A note edit can affect earlier body-page reservations. Until dependencies
    # are proven equal, no body checkpoint is safe, even before its reference.
    if previous and (
        previous.coordination != coordination or (pager and previous.resources != resources)
    ):
        previous = None
    check_cancel(cancelled)
    common = 0
    if previous:
        for old, new in zip(previous.inputs, inputs):
            check_cancel(cancelled)
            if old != new:
                break
            common += 1
        # A heading probes all subsequent headings and the first following
        # non-heading. Rewind that whole chain when its lookahead has changed.
        while common and measured[common - 1][0].keep_next:
            common -= 1
    suffix = 0
    if previous and cache.suffix_enabled:
        while suffix < min(len(inputs), len(previous.inputs)) - common:
            check_cancel(cancelled)
            if inputs[-suffix - 1] != previous.inputs[-suffix - 1]:
                break
            suffix += 1
    return Prepared(
        cache,
        key,
        inputs,
        previous,
        common,
        resources,
        suffix,
        coordination,
    )


def suffix_boundary(prepared, index, current):
    """Return the old block index only after input AND pagination convergence."""
    if prepared is None or index < len(prepared.inputs) - prepared.suffix:
        return None
    old_index = index + len(prepared.previous.inputs) - len(prepared.inputs)
    old = prepared.previous.checkpoints[old_index]
    return old_index if current.position() == old.position() else None


def suffix_checkpoints(previous, old_index, current):
    """Rebase buffer/diagnostic offsets, without touching geometry or source spans."""
    boundary = previous.checkpoints[old_index]
    for old in previous.checkpoints[old_index:]:
        same_page = old.page == boundary.page
        yield replace(
            old,
            fragments=old.fragments + (current.fragments - boundary.fragments if same_page else 0),
            ops=old.ops + (current.ops - boundary.ops if same_page else 0),
            images=old.images + (current.images - boundary.images if same_page else 0),
            diagnostics=old.diagnostics + current.diagnostics - boundary.diagnostics,
            footnotes=replace(
                old.footnotes,
                diagnostics=old.footnotes.diagnostics
                + current.footnotes.diagnostics
                - boundary.footnotes.diagnostics,
            )
            if old.footnotes is not None
            else None,
        )


def publish(
    prepared,
    checkpoints,
    pages,
    diagnostics,
    cancelled,
    *,
    suffix_reused=0,
    body_pages=None,
    pager=None,
):
    if prepared is None:
        return
    cache, key, inputs = prepared.cache, prepared.key, prepared.inputs
    previous, common = prepared.previous, prepared.common
    check_cancel(cancelled)
    weights = list(previous.input_weights[:common]) if common else []
    for value in inputs[common : len(inputs) - prepared.suffix]:
        check_cancel(cancelled)
        weights.append(_weight(value, exclude_glyphs=True, check=lambda: check_cancel(cancelled)))
    if prepared.suffix:
        weights.extend(previous.input_weights[-prepared.suffix :])
    resource_weight = (
        previous.resource_weight
        if previous and previous.resources == prepared.resources
        else _weight(prepared.resources, check=lambda: check_cancel(cancelled))
    )
    result = Continuation(
        inputs,
        tuple(checkpoints),
        body_pages if body_pages is not None else pages,
        tuple(diagnostics),
        tuple(weights),
        prepared.resources,
        resource_weight,
        pages,
        prepared.coordination,
        tuple(pager.pages) if pager else (),
        tuple(pager.diagnostics) if pager else (),
    )
    # Geometry storage dominates; count points conservatively without traversing
    # every float. Reuse validated prefix weights; account for the resource
    # catalog once, independently of the number of boxes referring to its glyphs.
    weight = (
        sum(weights)
        + resource_weight
        + 16 * len(inputs)
        + _weight(
            key,
            result.checkpoints,
            result.diagnostics,
            result.coordination,
            result.note_pages,
            result.note_diagnostics,
            check=lambda: check_cancel(cancelled),
        )
    )
    for page in pages:
        check_cancel(cancelled)
        weight += 512 * len(page.fragments)
        weight += 128 * sum(len(op.points) for op in (*page.paint_ops, *page.preview_ops))
        weight += sum(len(image.png_base64 or "") + 512 for image in page.images)
        weight += len(page.background.png_base64) if page.background else 0
    if body_pages is not None:
        # Template finalization shares point/fragment objects with the raw body,
        # but retains distinct PaintOps, Page objects and reference arrays.
        weight += sum(512 + 256 * len(p.paint_ops) + 16 * len(p.fragments) for p in body_pages)
    check_cancel(cancelled)
    cache.put((key,), result, weight)
    reused_pages = previous.checkpoints[common].page if common else 0
    if suffix_reused:
        boundary = checkpoints[len(inputs) - suffix_reused]
        reused_pages += len(pages) - boundary.page - 1
    cache.record(common, suffix_reused, len(inputs) - common - suffix_reused, reused_pages)
    check_cancel(cancelled)
