"""Bounded request-independent parse and full-layout caches; never authoritative storage."""

from dataclasses import asdict, dataclass

from ..cache import BoundedCache
from ..document.limits import policy_key
from ..document.markdown import dialect_version
from ..document.schema import digest
from ..layout.continuation import ContinuationCache
from ..layout.measurement_cache import MeasurementCache
from ..math.schema import MATH_VERSION

CACHE_VERSION = "markdown-build-cache-v1"


@dataclass(frozen=True)
class CachedLayout:
    snapshot: object
    selections: tuple


class MarkdownBuildCache:
    def __init__(self):
        self.parsed = BoundedCache(max_entries=4, max_weight=16 * 1024**2)
        self.resources = BoundedCache(max_entries=256, max_weight=32 * 1024**2)
        self.font_trajectories = BoundedCache(max_entries=4096, max_weight=64 * 1024**2)
        self.layouts = BoundedCache(max_entries=2, max_weight=192 * 1024**2)
        self.routes = BoundedCache(max_entries=128, max_weight=16 * 1024**2)
        self.measurements = MeasurementCache()
        self.continuation = ContinuationCache()

    def statistics(self):
        return {
            name: getattr(self, name).statistics()
            for name in ("parsed", "resources", "font_trajectories", "layouts", "routes", "measurements", "continuation")
        }


def source_key(session, dialect):
    return (
        CACHE_VERSION,
        policy_key(),
        dialect_version(dialect),
        MATH_VERSION,
        session.document_id,
        session.source,
        session.atom_ids,
    )


def layout_key(source, resolver, page, style, flow):
    from ..layout.blocks import LAYOUT_VERSION
    from ..layout.footnotes import VERSION as FOOTNOTE_VERSION
    from ..layout.template_fields import VERSION as FIELD_VERSION
    from ..math.handwritten import MATH_LAYOUT_VERSION

    # Frozen descriptors include geometry, metrics, provider, source bytes and pool
    # order. Asset IDs or user-supplied calibration labels alone are insufficient.
    pools = tuple((char, resolver.pools[char]) for char in sorted(resolver.pools))
    selections = tuple(sorted(resolver.selections.values(), key=lambda s: s.occurrence_id))
    # Python equality conflates 1/1.0/True and signed zero; serialized profiles
    # distinguish them in snapshot IDs. Use the same exact JSON representation.
    settings = digest(
        {"page": asdict(page), "style": asdict(style), "flow": flow.layout_record(), "seed": resolver.seed}
    )
    return (
        source,
        pools,
        selections,
        resolver.font_identity,
        settings,
        LAYOUT_VERSION,
        MATH_LAYOUT_VERSION,
        FOOTNOTE_VERSION,
        FIELD_VERSION,
    )


def parsed_weight(session, document):
    nodes = [n for root in document.nodes for n in root.walk()]
    return (
        len(session.source.encode())
        + len(session.atom_ids) * 96
        + len(nodes) * 384
        + sum(len(n.occurrences) for n in nodes) * 384
        + sum(sum(1 for _ in n.math.walk()) for n in nodes if n.math) * 384
    )


def snapshot_weight(snapshot, session, resolver):
    # Keys retain the complete immutable resource catalog and identity registry,
    # including glyphs not painted on these pages. Account for those references.
    key_weight = len(session.source.encode()) + len(session.atom_ids) * 96
    key_weight += len(resolver.selections) * 384
    key_weight += sum(
        len(g.original_json) + 512 + sum(map(len, g.strokes)) * 128
        for pool in resolver.pools.values()
        for g in pool
    )
    return key_weight + sum(
        512 * len(p.fragments)
        + 128 * sum(len(o.points) for o in (*p.paint_ops, *p.preview_ops))
        + sum(len(i.png_base64 or "") for i in p.images)
        + (len(p.background.png_base64) if p.background else 0)
        for p in snapshot.pages
    )
