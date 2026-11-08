"""Exact coordinate rounding and collision-safe page cache identity."""

import random
import xml.etree.ElementTree as ET
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from inkstruct.assets.resolver import AssetResolver
from inkstruct.cache import BoundedCache
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.layout.blocks import layout_markdown
from inkstruct.renderers import pages


def snapshot():
    return layout_markdown(
        parse_markdown(SourceSession("12.34")), AssetResolver(builtin_numbers=True)
    )


def test_preview_cache_hash_collision_does_not_alias_changed_page(monkeypatch):
    original = snapshot()
    page = original.pages[0]
    changed = replace(
        original,
        pages=(replace(page, paint_ops=(replace(page.paint_ops[0], width_mm=0.8),)),),
    )
    monkeypatch.setattr(pages, "hash", lambda content: 7, raising=False)
    cache = BoundedCache(max_entries=2, max_weight=1000)
    first = pages.preview_key(original, 0)
    second = pages.preview_key(changed, 0)
    assert hash(first) == hash(second) and first != second
    cache.put((first,), "original", 1)
    cache.put((second,), "changed", 1)
    assert cache.get(pages.preview_key(replace(original, revision=5), 0)) == "original"
    assert cache.get(pages.preview_key(replace(changed, revision=6), 0)) == "changed"
    assert pages.page_svg(original, 0) != pages.page_svg(changed, 0)


def test_preview_coordinates_keep_six_decimal_half_even_rounding():
    rng = random.Random(415)
    values = [
        0.0,
        -0.0,
        0.0000005,
        -0.0000005,
        0.0000015,
        -0.0000015,
        1.2345675,
        -1.2345675,
        1e-100,
        -1e-100,
        1e100,
        -1e100,
        *[rng.uniform(-1000, 1000) for _ in range(500)],
    ]
    points = tuple((value, -value) for value in values)
    original = snapshot()
    page = original.pages[0]
    custom = replace(
        original, pages=(replace(page, paint_ops=(replace(page.paint_ops[0], points=points),)),)
    )
    node = ET.fromstring(pages.page_svg(custom, 0)).find("{http://www.w3.org/2000/svg}polyline")
    with localcontext() as context:
        context.prec = 120

        def reference(value):
            return str(Decimal.from_float(value).quantize(Decimal("0.000001"), ROUND_HALF_EVEN))

        expected = [f"{reference(x)},{reference(y)}" for x, y in points]
    assert node.attrib["points"].split() == expected
