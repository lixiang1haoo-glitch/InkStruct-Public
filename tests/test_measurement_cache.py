"""Measurement reuse keeps source mappings, selection effects and current resources."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from test_math_sample_constructions import assets as construction_assets

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.code_style import CodeStyle
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import Occurrence, SourceSpan, StyleProfile
from inkstruct.document.tables import table_model
from inkstruct.layout.code import measure_code
from inkstruct.layout.inline import InlineRun, LayoutCancelled, measure_runs
from inkstruct.layout.measurement_cache import MeasurementCache, measurement_scope
from inkstruct.layout.tables import measure_table
from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle


def runs():
    return [
        InlineRun(Occurrence(f"o{i}", "node", SourceSpan(i, i + 1), c))
        for i, c in enumerate("12.50")
    ]


def resolver(**kwargs):
    return AssetResolver(embedded=construction_assets()[:1], builtin_numbers=True, **kwargs)


@pytest.mark.parametrize("kind", ["inline", "math", "code", "table"])
def test_reuse_replays_selections_and_skips_geometry(kind, monkeypatch):
    source = SourceSession("$\\frac{12}{34}$\n\n|12|34|\n|---|---|\n|5.6|7.8|")
    doc = parse_markdown(source)
    if kind == "inline":
        call = lambda r: measure_runs(runs(), r, StyleProfile())
    elif kind == "code":
        call = lambda r: measure_code(runs(), r, StyleProfile(), CodeStyle())
    elif kind == "math":
        node = next(n for root in doc.nodes for n in root.walk() if n.math)
        call = lambda r: measure_math(node.math, r, owner=node.node_id)
    else:
        table = table_model(next(n for n in doc.nodes if n.kind == "table"))
        call = lambda r: measure_table(table, r)
    c, original = MeasurementCache(), resolver()
    with measurement_scope(c):
        first = call(original)
    assert original.selections
    # Replaying resources is required; geometry work must not run again.
    from inkstruct.assets.symbol_provider import ResolvedGlyph

    def forbidden(g):
        raise AssertionError("measurement geometry was not reused")

    monkeypatch.setattr(ResolvedGlyph, "bounds", property(forbidden))
    fresh = resolver()
    with measurement_scope(c):
        hit = call(fresh)
    assert hit == first and fresh.selection_records() == original.selection_records()
    assert c.statistics()["hits"] >= 1
    # Mutable list/set containers returned by inline/code do not belong to cache.
    if kind in {"inline", "code"}:
        first[0].clear()
        hit[0].clear()
        if kind == "code":
            hit[2].add(99)
        with measurement_scope(c):
            again = call(resolver())
        assert again[0]
        if kind == "code":
            assert 99 not in again[2]


@pytest.mark.parametrize(
    "change", ["geometry", "metrics", "provenance", "selection", "missing", "incompatible"]
)
def test_dependency_changes_use_current_resources(change):
    r = resolver()
    one = r.pools["1"][0]
    c = MeasurementCache()
    rr = runs()[:1]
    with measurement_scope(c):
        measure_runs(rr, r, StyleProfile())
    selections = tuple(r.selections.values())
    if change == "geometry":
        g = replace(one, strokes=(((0.1, 0.2), (0.3, 0.8)),))
    elif change == "metrics":
        g = replace(one, metrics=replace(one.metrics, advance=one.metrics.advance + 0.2))
    elif change == "provenance":
        g = replace(one, original_json=one.original_json + b" ")
    elif change == "selection":
        g = replace(one, asset_id="alternate", sample_id="alternate")
        selections = (replace(selections[0], asset_id=g.asset_id, sample_id=g.sample_id),)
    else:
        g = one
        if change == "incompatible":
            selections = (replace(selections[0], character="2"),)

    def current():
        return AssetResolver(embedded=() if change == "missing" else (g,), selections=selections)

    expected_resolver = current()
    expected = measure_runs(rr, expected_resolver, StyleProfile())
    actual_resolver = current()
    with measurement_scope(c):
        actual = measure_runs(rr, actual_resolver, StyleProfile())
    assert actual == expected
    assert actual_resolver.selection_records() == expected_resolver.selection_records()
    assert c.statistics()["invalidations"] == 1 and c.statistics()["hits"] == 0


@pytest.mark.parametrize(
    "change",
    ["span", "identity", "size", "character_em", "pen", "version", "numeric_type", "signed_zero"],
)
def test_source_style_and_version_inputs_are_exact(change, monkeypatch):
    from inkstruct.layout import measurement_cache

    c, rr, style = MeasurementCache(), runs(), StyleProfile()
    options = {"scale": 1, "character_em": {"1": 6.0}, "math_style": MathStyle(axis_em=0.0)}
    with measurement_scope(c):
        measure_runs(rr, resolver(), style, **options)
    if change == "span":
        rr = [
            replace(r, occurrence=replace(r.occurrence, span=SourceSpan(20 + i, 21 + i)))
            for i, r in enumerate(rr)
        ]
    elif change == "identity":
        rr = [
            replace(
                r,
                occurrence=replace(r.occurrence, occurrence_id="new-" + r.occurrence.occurrence_id),
            )
            for r in rr
        ]
    elif change == "size":
        options["scale"] = 1.2
    elif change == "character_em":
        options["character_em"] = {"1": 7.0}
    elif change == "pen":
        style = replace(style, stroke_width_mm=0.4)
    elif change == "numeric_type":
        options["scale"] = 1.0
    elif change == "signed_zero":
        options["math_style"] = MathStyle(axis_em=-0.0)
    else:
        monkeypatch.setattr(measurement_cache, "MEASUREMENT_VERSION", "changed")
    expected = measure_runs(rr, resolver(), style, **options)
    with measurement_scope(c):
        actual = measure_runs(rr, resolver(), style, **options)
    assert actual == expected and c.statistics()["hits"] == 0


def test_missing_is_retried_and_cancellation_never_publishes_partial_measurement():
    c = MeasurementCache()
    with measurement_scope(c):
        missing = measure_runs(runs(), AssetResolver(), StyleProfile())
    assert missing[1] and c.statistics()["entries"] == 0
    event = threading.Event()

    class CancellingResolver:
        def __init__(self):
            self.real = resolver()

        def resolve(self, occurrence):
            event.set()
            return self.real.resolve(occurrence)

    with measurement_scope(c), pytest.raises(LayoutCancelled):
        measure_runs(runs(), CancellingResolver(), StyleProfile(), cancelled=event)
    assert c.statistics()["entries"] == 0
    event.clear()
    with measurement_scope(c):
        expected = measure_runs(runs(), resolver(), StyleProfile(), cancelled=event)
    event.set()
    with measurement_scope(c), pytest.raises(LayoutCancelled):
        measure_runs(runs(), resolver(), StyleProfile(), cancelled=event)
    assert c.statistics()["hits"] == 0
    event.clear()
    with measurement_scope(c):
        assert measure_runs(runs(), resolver(), StyleProfile(), cancelled=event) == expected


def test_scopes_are_thread_local_reset_after_error_and_obey_capacity():
    c = MeasurementCache(max_entries=1)
    with measurement_scope(c):
        measure_runs(runs(), resolver(), StyleProfile())
        measure_runs(runs(), resolver(), StyleProfile(em_mm=7))
        measure_runs(runs(), resolver(), StyleProfile())
    assert c.statistics()["evictions"] == 2 and c.statistics()["hits"] == 0
    before = c.statistics()
    with pytest.raises(RuntimeError), measurement_scope(c):
        raise RuntimeError("exit scope")
    measure_runs(runs(), resolver(), StyleProfile())
    assert c.statistics() == before
    tiny = MeasurementCache(max_weight=1)
    with measurement_scope(tiny):
        measure_runs(runs(), resolver(), StyleProfile())
    assert tiny.statistics()["entries"] == 0 and tiny.statistics()["skipped"] == 1
    barrier = threading.Barrier(2)

    def worker(_):
        own = MeasurementCache()
        with measurement_scope(own):
            measure_runs(runs(), resolver(), StyleProfile())
            barrier.wait(timeout=5)
            measure_runs(runs(), resolver(), StyleProfile())
        return own.statistics()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(worker, range(2)))
    assert all(r["hits"] == 1 and r["misses"] == 1 for r in results)


def test_shared_resource_budget_follows_last_reference_and_clear():
    c, r = MeasurementCache(max_entries=2), resolver()
    one = runs()[:1]
    with measurement_scope(c):
        measure_runs(one, r, StyleProfile())
        first_weight = c.weight
        measure_runs(one, r, StyleProfile(em_mm=7))
        assert c.statistics()["shared_resources"] == 1
        assert first_weight < c.weight < 2 * first_weight
        measure_runs(runs()[1:2], r, StyleProfile())
        assert c.statistics()["shared_resources"] == 2  # One remaining use of 1, plus 2.
        measure_runs(runs()[1:2], r, StyleProfile(em_mm=7))
        assert c.statistics()["shared_resources"] == 1  # Last use of 1 was evicted.
    assert c.weight == sum(e.weight for e in c._entries.values()) + sum(
        v[2] for v in c._resources.values()
    )
    c.clear()
    assert c.weight == 0 and c.statistics()["shared_resources"] == 0


def test_cancel_at_cache_insert_does_not_return_result_and_keeps_only_complete_entry():
    event = threading.Event()

    class CancelAtInsert(MeasurementCache):
        def put(self, *args, **kwargs):
            super().put(*args, **kwargs)
            event.set()

    c = CancelAtInsert()
    with measurement_scope(c), pytest.raises(LayoutCancelled):
        measure_runs(runs(), resolver(), StyleProfile(), cancelled=event)
    event.clear()
    with measurement_scope(c):
        hit = measure_runs(runs(), resolver(), StyleProfile(), cancelled=event)
    assert hit == measure_runs(runs(), resolver(), StyleProfile())
    assert c.statistics()["entries"] == 1 and c.statistics()["hits"] == 1
