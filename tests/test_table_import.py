import json
from dataclasses import asdict, replace

import pytest
from test_table_samples import make_archive

from inkstruct.cli import main
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.table_import import import_table_project
from inkstruct.layout.blocks import layout_markdown
from inkstruct.table_editor.core import Settings
from inkstruct.table_editor.samples import load_sample_zip


def legacy_project(root, *, samples=True):
    value = {
        "schema_version": "inkstruct_table_v1",
        "html": "<table><tr><td>001.20</td><td>1.20</td></tr><tr><td>0.005</td><td>8</td></tr></table>",
        "settings": asdict(Settings()),
        "routing": {"optimize": True, "allow_reverse": False},
    }
    if samples:
        archive = root / "samples.zip"
        make_archive(archive)
        value["samples"] = {
            "path": archive.name,
            "sha256": load_sample_zip(archive).sha256,
            "seed": 42,
        }
    path = root / "old.inktable"
    path.write_text(json.dumps(value))
    return path, value


def snapshot(loaded):
    return layout_markdown(
        parse_markdown(loaded.session),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )


@pytest.mark.parametrize("samples", [False, True])
def test_legacy_import_preserves_values_choices_dimensions_and_is_portable(tmp_path, samples):
    path, value = legacy_project(tmp_path, samples=samples)
    raw = path.read_bytes()
    loaded = import_table_project(path)
    result = snapshot(loaded)
    assert result.exportable, result.diagnostics
    assert loaded.session.source == value["html"] and path.read_bytes() == raw
    assert loaded.optimize  # Existing optimization implies reversal under the new policy.
    assert loaded.flow.table.numeric_spacing == "legacy-ink"
    assert (
        loaded.flow.table.width_mm,
        loaded.flow.table.min_row_height_mm,
        loaded.flow.table.digit_height_mm,
        loaded.flow.table.padding_top_mm,
    ) == (160, 8, 3.8, 0.3)
    assert "".join(f.text for f in result.fragments) == "001.201.200.0058"
    if samples:
        bank = load_sample_zip(tmp_path / "samples.zip").select(42)
        for occurrence in parse_markdown(loaded.session).occurrences:
            bank[occurrence.text]
            choice = loaded.resolver.selections[occurrence.occurrence_id]
            selected = bank.trace[-1]["sample_id"]
            assert choice.sample_id == selected or (
                selected == "builtin:decimal-point" and occurrence.text == "."
            )
    target = tmp_path / "new.inkdoc"
    save_package(
        target,
        loaded.session,
        loaded.resolver,
        loaded.page,
        loaded.style,
        flow=loaded.flow,
        optimize=loaded.optimize,
    )
    if samples:
        (tmp_path / "samples.zip").unlink()
    reopened = load_package(target)
    assert snapshot(reopened) == result
    assert reopened.flow == loaded.flow and path.read_bytes() == raw


@pytest.mark.parametrize("change", ["seed", "hash", "missing", "schema", "settings"])
def test_legacy_import_rejects_invalid_or_changed_inputs(tmp_path, change):
    path, value = legacy_project(tmp_path)
    if change == "seed":
        value["samples"]["seed"] = True
    elif change == "hash":
        value["samples"]["sha256"] = "0" * 64
    elif change == "missing":
        (tmp_path / "samples.zip").unlink()
    elif change == "schema":
        value["schema_version"] = "unknown"
    else:
        value["settings"]["digit_height"] = -1
    path.write_text(json.dumps(value))
    raw = path.read_bytes()
    with pytest.raises((ValueError, OSError)):
        import_table_project(path)
    assert path.read_bytes() == raw


def test_table_subset_has_distinct_content_key_but_keeps_source_and_identity():
    document = parse_markdown("Before\n\n|1|\n|---|\n|2|\n\nAfter")
    node = next(n for n in document.nodes if n.kind == "table")
    selected = replace(document, nodes=(node,))
    assert selected.content_key != document.content_key
    assert selected.source == document.source
    assert selected.occurrences == tuple(o for o in document.occurrences if o.text in "12")


def test_cli_legacy_import_and_portable_reopen_produce_identical_svg(tmp_path, capsys):
    path, _ = legacy_project(tmp_path)
    first, second, project = (tmp_path / name for name in ("first", "second", "new.inkdoc"))
    assert (
        main(
            [
                "document",
                "render",
                str(path),
                "--plotter",
                "--output",
                str(first),
                "--save-project",
                str(project),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["exportable"]
    (tmp_path / "samples.zip").unlink()
    assert main(["document", "render", str(project), "--plotter", "--output", str(second)]) == 0
    assert (first / "page-001.svg").read_bytes() == (second / "page-001.svg").read_bytes()
