"""The v6.3.1 desktop route owns its generation policies and reads v6.3 archives."""
import ast
from pathlib import Path

import pytest

from inkstruct import generation_workflow as workflow
from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font, generated_records
from inkstruct.layout.blocks import layout_markdown
from inkstruct.samples import sha256_file
from inkstruct.v631.engine import ENGINE_VERSION

from test_v63_connected import record

pytest_plugins = ("test_v63_connected",)


def test_new_policy_package_does_not_import_legacy_engines():
    from inkstruct import v631

    root = Path(v631.__file__).parent
    shared = {"component_style", "contextual_trajectory", "generation_workflow", "geometry",
              "geometry_audit", "profile", "samples", "schemas",
              "source_trajectory", "structure_corrections", "structures", "topology_repair",
              "trajectory_experiment", "v63_package"}
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 2:
                assert node.module in shared, (path, node.module)
                if node.module == "generation_workflow":
                    assert {name.name for name in node.names} <= {
                        "code_hashes", "connected_profile_valid", "corrections", "read", "write",
                    }


def test_old_archive_reuse_and_distinct_publication(setup, tmp_path, monkeypatch):
    from inkstruct import v63, v62_exp

    repo, graph, refs = setup
    monkeypatch.setattr(workflow, "corrections", lambda: refs)
    source = tmp_path / "raw"
    record(source / "connected.json", graph, join=0)
    old = workflow.GenerationWorkflow(tmp_path / "old", repo.path)
    legacy = old.generate("alice", source, "v63", "明", workers=1, candidate_limit=1,
                          preparation=lambda *_: None)
    whole = old.state("alice", source)
    profile = whole["profiles"]["v63"]
    original = {Path(p): sha256_file(Path(p)) for p in (
        profile["path"], profile["connected"]["path"], whole["import"]["index"], old.state_path("alice", source)
    )}
    def unsupported(*args, **kwargs):
        pytest.fail("v6.3.1 called a legacy policy")
    for owner, name in (
        (workflow, "prepare_generation"),
        (v63, "build_connected_profile"),
        (v63, "same_character_candidates"),
        (v63, "connected_candidates"),
        (v62_exp, "SemanticCandidateGenerator"),
        (v62_exp, "SemanticBatchStrokeFallback"),
    ):
        monkeypatch.setattr(owner, name, unsupported)
    stages = []
    result = old.generate("alice", source, "v631", "明", workers=1, candidate_limit=1,
                          preparation=lambda stage, _: stages.append(stage), source_score=True)
    assert "沿用档案" in stages and "建档" not in stages
    assert result["scores"]["source_score"] == 100
    assert all(sha256_file(path) == digest for path, digest in original.items())

    def inspect(batch):
        root = Path(batch["output"])
        protocol = workflow.read(root / "protocol.json")
        glyph, _, _, _ = next(generated_records(root, "alice"))
        assert glyph["method"] == "same_character"
        return root, protocol, glyph

    _, legacy_protocol, legacy_glyph = inspect(legacy)
    root, protocol, glyph = inspect(result)
    assert legacy_protocol["method"] == legacy_glyph["generator"] == "v6.3 exp"
    assert protocol["method"] == glyph["generator"] == "v6.3.1"
    assert protocol["version"] == ENGINE_VERSION
    assert glyph["segments"] == legacy_glyph["segments"]

    direct = old.generate("alice", source, "v631", "明", workers=1, candidate_limit=1)
    assert inspect(direct)[2] == glyph
    font = tmp_path / "connected.inkfont"
    build_font(font, writer="alice", name="v6.3.1 connected", run=root)
    assets = list(FontPackage(font).glyphs())
    assert assets[0].font_metadata["summary"]["generation_method"] == "v6.3.1"
    session = SourceSession("明")
    resolver = AssetResolver(embedded=assets)
    layout = layout_markdown(parse_markdown(session), resolver)
    doc = tmp_path / "frozen.inkdoc"
    save_package(doc, session, resolver, PageProfile(), StyleProfile())
    reloaded = load_package(doc)
    assert layout_markdown(parse_markdown(reloaded.session), reloaded.resolver) == layout
    assert reloaded.resolver.selection_records() == resolver.selection_records()

    fresh = workflow.GenerationWorkflow(tmp_path / "new", repo.path)
    independent = fresh.generate("alice", source, "v631", "明", workers=1, candidate_limit=1,
                                 preparation=lambda *_: None)
    assert fresh.state("alice", source)["profiles"]["v631"]["method"] == "v631"
    assert inspect(independent)[2] == glyph


def test_new_method_refuses_modified_connected_archive(setup, tmp_path, monkeypatch):
    repo, graph, refs = setup
    monkeypatch.setattr(workflow, "corrections", lambda: refs)
    source = tmp_path / "raw"
    record(source / "connected.json", graph, join=0)
    service = workflow.GenerationWorkflow(tmp_path / "work", repo.path)
    service.update_samples("alice", source, "v63")
    old = service.state("alice", source)
    archive = Path(old["profiles"]["v63"]["connected"]["path"])
    archive.write_bytes(archive.read_bytes() + b" ")
    with pytest.raises(ValueError, match="连笔档案已改变"):
        service.generate("alice", source, "v631", "明", workers=1, candidate_limit=1)
    assert service.state("alice", source) == old
