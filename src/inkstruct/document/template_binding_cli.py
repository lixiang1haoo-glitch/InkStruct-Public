"""Explicit agent bindings using the same native identities and layout as the editor."""

import json
from dataclasses import asdict, replace

from ..layout.blocks import layout_markdown
from .markdown import parse_markdown
from .package import load_package, save_package
from .template import TemplateBinding
from .template_authoring import read_template

REQUEST_VERSION = "inkstruct_template_binding_request_v1"
SLOT_REQUEST_VERSION = "inkstruct_template_slot_request_v1"
MAX_REQUEST_BYTES = 2 * 1024 * 1024


def read_bindings(path, project_hash, template=None):
    with path.open("rb") as stream:
        raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("Binding request exceeds 2 MiB")
    value = json.loads(raw)
    if isinstance(value, dict) and value.get("schema_version") == SLOT_REQUEST_VERSION:
        return read_slot_request(value, project_hash, template)
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "project_sha256",
        "bindings",
    }:
        raise ValueError(
            "Binding request requires schema_version, project_sha256 and bindings only"
        )
    if value["schema_version"] != REQUEST_VERSION:
        raise ValueError("Unsupported binding request version")
    if value["project_sha256"] != project_hash:
        raise ValueError("Project changed since inspection; inspect it again before binding")
    records = value["bindings"]
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError("Bindings must be a list of at most 1000 entries")
    if any(not isinstance(record, dict) for record in records):
        raise TypeError("Each binding must be a JSON object")
    return tuple(TemplateBinding(**record) for record in records)


def read_slot_request(value, project_hash, template):
    if set(value) != {"schema_version", "project_sha256", "slots", "bindings"}:
        raise ValueError("Slot request requires schema_version, project_sha256, slots and bindings")
    if value["project_sha256"] != project_hash:
        raise ValueError("Project changed since inspection; inspect it again before binding")
    declarations = {s.slot_id: s for s in getattr(template, "slots", ())}
    if not declarations:
        raise ValueError("Template has no semantic field declarations")
    slots, records = value["slots"], value["bindings"]
    if (
        not isinstance(slots, list)
        or not isinstance(records, list)
        or len(slots) + len(records) > 1000
    ):
        raise ValueError("Slot request must contain at most 1000 total mappings")
    result, seen = [], set()
    for record in slots:
        if not isinstance(record, dict) or set(record) != {"slot_id", "node_ids"}:
            raise ValueError("Slot mapping requires slot_id and node_ids only")
        key = record["slot_id"]
        if not isinstance(key, str) or key not in declarations or key in seen:
            raise ValueError("Unknown or duplicate slot ID")
        seen.add(key)
        result.append(declarations[key].bind(record["node_ids"]))
    regions = {s.region for s in declarations.values()}
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("Each binding must be a JSON object")
        binding = TemplateBinding(**record)
        if binding.region in regions:
            raise ValueError("Declared fields must use slot mappings in a slot request")
        result.append(binding)
    return tuple(result)


def inspect_content(loaded, document, flow):
    template = flow.template
    bound = {node_id: b.region for b in flow.template_bindings for node_id in b.node_ids}
    report = {
        "kind": "template-content-inspection",
        "project_sha256": loaded.file_hash,
        "document_id": loaded.session.document_id,
        "revision": loaded.session.revision,
        "dialect": flow.markdown_dialect,
        "content_fit_checked": False,
        "machine_export_ready": False,
        "binding_policy": "replace-all; omitted blocks return to body; source order is preserved",
        "binding_request": {
            "schema_version": REQUEST_VERSION,
            "project_sha256": loaded.file_hash,
            "bindings": [asdict(b) for b in flow.template_bindings],
        },
        "nodes": [
            {
                "node_id": n.node_id,
                "kind": n.kind,
                "span": asdict(n.span),
                "source": document.source[n.span.start : n.span.end],
                "bindable": n.kind != "footnote_definition",
                "bound_region": bound.get(n.node_id),
            }
            for n in document.nodes
        ],
        "template": None
        if template is None
        else {
            "name": template.name,
            "schema_version": template.schema_version,
            "faces": {} if flow.named_fields else {
                name: {
                    "body": asdict(getattr(template, name).body),
                    "regions": [asdict(r) for r in getattr(template, name).reserved],
                    "anchors": [asdict(a) for a in getattr(template, name).anchors],
                }
                for name in ("first", "continuation")
            },
        },
        "diagnostics": [asdict(d) for d in document.diagnostics],
    }
    if flow.named_fields:
        report['template']['layouts']=[asdict(p) for p in template.layouts]
        report['template']['fields']=[asdict(f) for f in template.fields]
        report['template']['start_pages']=template.start_pages
        report['template']['loop_pages']=template.loop_pages
        report['template']['markdown_skeleton']=template.skeleton()
    slots = getattr(template, "slots", ())
    report["slots"] = [asdict(s) for s in slots]
    if slots:
        by_region = {b.region: b for b in flow.template_bindings}
        regions = {s.region for s in slots}
        report["slot_request"] = {
            "schema_version": SLOT_REQUEST_VERSION,
            "project_sha256": loaded.file_hash,
            "slots": [
                {"slot_id": s.slot_id, "node_ids": list(by_region[s.region].node_ids)}
                for s in slots
                if s.region in by_region
            ],
            "bindings": [asdict(b) for b in flow.template_bindings if b.region not in regions],
        }
    return report


def run_binding_command(args):
    if args.source.suffix.lower() != ".inkdoc":
        raise ValueError("Use a saved .inkdoc project so node identities and resources stay stable")
    loaded = load_package(args.source)
    flow = loaded.flow
    if args.template:
        flow = replace(flow, template=read_template(args.template))
    document = parse_markdown(loaded.session, dialect=flow.markdown_dialect,field_blocks=flow.named_fields)
    if flow.named_fields and args.template_action=='bind':
        raise ValueError('Template v3 uses explicit :::field blocks in the authoritative Markdown, not legacy node binding requests')
    if args.template_action == "inspect-content":
        return 0, inspect_content(loaded, document, flow)
    if args.template_action == "bind":
        if args.output.suffix.lower() != ".inkdoc":
            raise ValueError("Output must be a new .inkdoc project")
        # lexists semantics also reject dangling symlinks. save_package checks again.
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Output already exists; choose a new .inkdoc path")
        flow = replace(
            flow, template_bindings=read_bindings(args.bindings, loaded.file_hash, flow.template)
        )
    page = flow.template.page if flow.template else loaded.page
    snapshot = layout_markdown(document, loaded.resolver, page=page, style=loaded.style, flow=flow)
    report = {
        "kind": "template-document-validation",
        "project_sha256": loaded.file_hash,
        "document_id": loaded.session.document_id,
        "content_fit_checked": True,
        "exportable": snapshot.exportable,
        "plotter_exportable": snapshot.plotter_exportable,
        "physical_alignment_verified": False,
        "pages": len(snapshot.pages),
        "occurrences": len(snapshot.fragments),
        "job_key": snapshot.job_key,
        "bindings": [asdict(b) for b in flow.template_bindings],
        "diagnostics": [asdict(d) for d in snapshot.diagnostics],
        "saved": False,
    }
    if flow.template is not None:
        from .template_fit import template_fit_report

        report["fit_report"] = template_fit_report(document, flow, snapshot)
    if args.template_action == "bind" and snapshot.exportable:
        output_hash = save_package(
            args.output,
            loaded.session,
            loaded.resolver,
            page,
            loaded.style,
            optimize=loaded.optimize,
            flow=flow,
            reviews=loaded.reviews,
        )
        report.update(saved=True, output=str(args.output.resolve()), output_sha256=output_hash)
    return (0 if snapshot.exportable else 2), report
