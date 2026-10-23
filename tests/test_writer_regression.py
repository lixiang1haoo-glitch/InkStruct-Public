import copy
import runpy
from pathlib import Path

helpers = runpy.run_path(str(Path(__file__).parents[1] / "scripts/check_writer_regression.py"))
compare = helpers["compare_archived_strokes"]


def test_archive_tolerance_is_only_last_pressure_decimal():
    original = [{"order": 1, "points": [{"x": 0.2, "y": 0.3, "t_ms": 1, "pressure": 0.123456}]}]
    assert compare(original, original) == "exact"
    changed = copy.deepcopy(original)
    changed[0]["points"][0]["pressure"] += 1e-6
    assert compare(original, changed) == "pressure_rounding_only"
    changed[0]["points"][0]["x"] += 1e-6
    assert compare(original, changed) == "mismatch"
    assert original[0]["points"][0]["pressure"] == 0.123456


def test_comparison_set_is_fixed_unique_and_balanced():
    characters = list("岛尴徹徼徽勾匈囊丢侈黧劓乌熟尬一二三四五六七八九十甲乙丙丁戊己庚辛壬癸")
    seen = set(characters[::2])
    selected = helpers["select_characters"](characters, seen, 24)
    assert selected == helpers["select_characters"](list(reversed(characters)), seen, 24)
    assert len(selected) == len(set(selected)) == 24
    assert sum(c in seen for c in selected) == 12
    assert set(helpers["CASES"]) <= set(selected)
