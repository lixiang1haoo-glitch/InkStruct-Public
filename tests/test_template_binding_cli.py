"""Agent binding is a checked native-project transaction, not copied field text."""

import json
from dataclasses import asdict, replace
from hashlib import sha256

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.cli import main
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Anchor, PageTemplate, Region, TemplateFace
from inkstruct.document.template_authoring import template_json
from inkstruct.editor.review import Review
from inkstruct.layout.blocks import layout_markdown


def project(tmp_path, width=110, source="12.3\n\n45.6\n\n78.9"):
    face = TemplateFace(
        Region("body", 10, 40, width - 20, 100),
        reserved=(Region("arbitrary-field", 10, 10, width - 20, 20),),
        anchors=(Anchor("baseline", 12, 18),),
    )
    template = PageTemplate("Generic test", width, 150, face, face)
    flow = FlowStyle(template=template, markdown_dialect="markdown")
    session = SourceSession(source)
    resolver = AssetResolver(builtin_numbers=True)
    layout_markdown(parse_markdown(session), resolver, flow=flow)
    path = tmp_path / "original.inkdoc"
    glyph = next(iter(resolver.pools.values()))[0]
    reviews = (
        asdict(
            Review(
                glyph.asset_id,
                glyph.character,
                "review",
                "retain",
                "",
                "",
                "",
                "",
                source,
                "hash",
                0,
                "now",
            )
        ),
    )
    save_package(
        path,
        session,
        resolver,
        template.page,
        StyleProfile(),
        flow=flow,
        optimize=True,
        reviews=reviews,
    )
    return path


def command(capsys, action, path, *options):
    code = main(["document", "template", action, str(path), *map(str, options)])
    return code, json.loads(capsys.readouterr().out)


def request(tmp_path, report, **changes):
    value = report["binding_request"]
    value["bindings"] = [
        {
            "region": "arbitrary-field",
            "node_ids": [report["nodes"][0]["node_id"]],
            "pages": "all",
            "anchor": "baseline",
            "scale": 0.654321098765,
        }
    ]
    value["bindings"][0].update(changes)
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize("width", [110, 210])
def test_inspect_bind_reopen_preserves_native_content_and_removal(tmp_path, capsys, width):
    path = project(tmp_path, width)
    original = path.read_bytes()
    before = load_package(path)
    code, report = command(capsys, "inspect-content", path)
    assert code == 0 and not report["content_fit_checked"]
    assert report["project_sha256"] == sha256(original).hexdigest()
    assert [n["source"] for n in report["nodes"]] == ["12.3\n", "45.6\n", "78.9"]
    assert report["dialect"] == "markdown"
    bindings = request(tmp_path, report)
    output = tmp_path / "bound.inkdoc"
    code, result = command(capsys, "bind", path, "--bindings", bindings, "--output", output)
    assert code == 0 and result["saved"] and result["plotter_exportable"]
    after = load_package(output)
    assert path.read_bytes() == original
    assert after.session.identity_record() == before.session.identity_record()
    assert after.session.source == before.session.source
    assert after.style == before.style and after.page == before.page
    assert after.reviews == before.reviews and after.optimize
    assert after.resolver.selections == before.resolver.selections
    assert after.resolver.pools == before.resolver.pools
    assert replace(after.flow, template_bindings=()) == before.flow
    snapshot = layout_markdown(parse_markdown(after.session), after.resolver, flow=after.flow)
    assert any(f.container_id == "template-field:arbitrary-field" for f in snapshot.fragments)
    code, checked = command(capsys, "validate-document", output)
    assert code == 0 and checked["job_key"] == result["job_key"]
    # Reinspect the new package; an explicit empty list removes all bindings.
    _, report = command(capsys, "inspect-content", output)
    report["binding_request"]["bindings"] = []
    bindings.write_text(json.dumps(report["binding_request"]))
    unbound = tmp_path / "unbound.inkdoc"
    code, _ = command(capsys, "bind", output, "--bindings", bindings, "--output", unbound)
    assert code == 0 and load_package(unbound).flow == before.flow


@pytest.mark.parametrize(
    "changes,diagnostic",
    [
        ({"node_ids": ["missing"]}, "template-binding-source-missing"),
        ({"region": "missing"}, "template-binding-region-missing"),
        ({"anchor": "missing"}, "template-binding-anchor-missing"),
    ],
)
def test_invalid_bindings_return_core_diagnostics_without_save(
    tmp_path, capsys, changes, diagnostic
):
    path = project(tmp_path)
    _, report = command(capsys, "inspect-content", path)
    bindings = request(tmp_path, report, **changes)
    output = tmp_path / "bad.inkdoc"
    code, result = command(capsys, "bind", path, "--bindings", bindings, "--output", output)
    assert code == 2 and not result["saved"] and not output.exists()
    assert diagnostic in {d["code"] for d in result["diagnostics"]}


def test_overflow_and_missing_glyph_are_not_silently_saved(tmp_path, capsys):
    path = project(tmp_path, source="1 " * 500 + "\n\n2")
    _, report = command(capsys, "inspect-content", path)
    bindings = request(tmp_path, report)
    output = tmp_path / "overflow.inkdoc"
    code, result = command(capsys, "bind", path, "--bindings", bindings, "--output", output)
    assert code == 2 and not output.exists()
    assert "template-field-height-overflow" in {d["code"] for d in result["diagnostics"]}
    missing = tmp_path / "missing"
    missing.mkdir()
    path = project(missing, source="汉字")
    code, report = command(capsys, "validate-document", path)
    assert code == 2 and not report["exportable"]


def test_stale_duplicate_and_unknown_requests_fail_without_overwrite(tmp_path, capsys):
    path = project(tmp_path)
    original = path.read_bytes()
    _, report = command(capsys, "inspect-content", path)
    bindings = request(tmp_path, report)
    good = bindings.read_bytes()
    output = tmp_path / "result.inkdoc"
    for key, value in [
        ("project_sha256", "stale"),
        ("schema_version", "future"),
        ("unexpected", 1),
    ]:
        data = json.loads(good)
        data[key] = value
        bindings.write_text(json.dumps(data))
        code, _ = command(capsys, "bind", path, "--bindings", bindings, "--output", output)
        assert code == 2 and not output.exists()
    data = json.loads(good)
    data["bindings"] *= 2
    bindings.write_text(json.dumps(data))
    code, _ = command(capsys, "bind", path, "--bindings", bindings, "--output", output)
    assert code == 2 and not output.exists()
    bindings.write_bytes(good)
    code, _ = command(capsys, "bind", path, "--bindings", bindings, "--output", path)
    assert code == 2 and path.read_bytes() == original
    try:
        output.symlink_to(tmp_path / "absent")
    except OSError as error:
        if getattr(error,'winerror',None)==1314:
            pytest.skip('Windows account lacks symbolic-link privilege; real dangling-link check unverified')
        raise
    code, _ = command(capsys, "bind", path, "--bindings", bindings, "--output", output)
    assert code == 2 and output.is_symlink() and not output.exists()


def test_replacement_template_and_native_only_contract(tmp_path, capsys):
    path = project(tmp_path)
    loaded = load_package(path)
    template = replace(
        loaded.flow.template, continuation=replace(loaded.flow.template.continuation, reserved=())
    )
    design = tmp_path / "new.json"
    design.write_text(template_json(template),encoding='utf-8')
    _, report = command(capsys, "inspect-content", path, "--template", design)
    assert report["template"]["faces"]["continuation"]["regions"] == []
    bindings = request(tmp_path, report)
    output = tmp_path / "new.inkdoc"
    code, result = command(
        capsys, "bind", path, "--template", design, "--bindings", bindings, "--output", output
    )
    assert code == 2 and not output.exists()
    assert "template-binding-region-missing" in {d["code"] for d in result["diagnostics"]}
    raw = tmp_path / "source.md"
    raw.write_text("123")
    code, result = command(capsys, "inspect-content", raw)
    assert code == 2 and ".inkdoc" in result["error"]
