"""A legacy library keeps its source intact while marks migrate to each local device."""
from dataclasses import asdict, replace
import json

from inkstruct.document.flow_template import FlowTemplate, PageLayout
from inkstruct.document.template_authoring import parse_template, template_json
from inkstruct.document.template_revision import version_template
from inkstruct.editor.machine_alignment import page_context
from inkstruct.plotter.profiles import DeviceProfile, PageAlignment, PlotterProfiles
from inkstruct.resource_catalog import TemplateStore


def test_read_only_legacy_library_migration(tmp_path):
    library = TemplateStore(tmp_path / "templates")
    template = version_template(FlowTemplate(kind="custom", layouts=(PageLayout("a", "甲"), PageLayout("b", "乙")),
                                             loop_pages=("a", "b")))
    source = tmp_path / "template.json"
    source.write_text(template_json(template), encoding="utf-8")
    entry = library.add(source)
    # Existing 0.1.138 installations stored mark overrides in this sidecar.
    sidecar = library.origins_dir / (entry["id"] + ".json")
    sidecar.parent.mkdir(exist_ok=True)
    raw = json.dumps([["a", asdict(PageAlignment((8, 9)))], ["b", asdict(PageAlignment((25, 30)))]])
    sidecar.write_text(raw, encoding="utf-8")
    old = library.read(entry)
    marks = {}
    for index in (0, 1):
        key, _, mark, _ = page_context(old, index=index)
        marks[key] = mark.a
    store = PlotterProfiles(tmp_path / "local")
    profile = DeviceProfile.create("N1", "COM1")
    store.import_marks(profile, marks)
    original = store.path.read_bytes()
    store.import_marks(profile, marks)
    assert store.path.read_bytes() == original
    for key, point in marks.items():
        assert store.sheet(profile, key) == {"mark": list(point)}
    exported = parse_template(template_json(old))
    assert exported.revision == template.revision
    assert exported.paper_origin(exported.layout(1)) is None
    assert sidecar.read_text("utf-8") == raw
    assert library.path(entry["id"]).read_bytes() == source.read_bytes()
