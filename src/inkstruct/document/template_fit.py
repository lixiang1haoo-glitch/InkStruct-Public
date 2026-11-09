"""Read-only fit evidence from the actual layout, shared by GUI and CLI."""

from collections import Counter
from dataclasses import asdict
from hashlib import sha256

from .schema import digest


def template_fit_report(document, flow, snapshot):
    if flow.template is None:
        raise ValueError("请先配置页面模板")
    if document.document_id != snapshot.document_id or document.revision != snapshot.revision:
        raise ValueError("排版结果已过期，请等待预览更新")
    template = flow.template
    if flow.named_fields:
        return flow_template_fit(document,flow,snapshot)
    slots = {s.region: s for s in getattr(template, "slots", ())}
    bindings = {b.region: b for b in flow.template_bindings}
    names = dict.fromkeys(
        [r.name for face in (template.first, template.continuation) for r in face.reserved]
        + list(slots)
        + list(bindings)
    )
    diagnostics = [asdict(d) for d in snapshot.diagnostics]
    by_region = {}
    for i, diagnostic in enumerate(snapshot.diagnostics):
        target = getattr(diagnostic, "target", None)
        if target:
            by_region.setdefault(target.region, []).append(i)
    fields = []
    for name in names:
        slot, binding = slots.get(name), bindings.get(name)
        indices = by_region.get(name, [])
        errors = sum(snapshot.diagnostics[i].severity == "error" for i in indices)
        warnings = sum(snapshot.diagnostics[i].severity == "warning" for i in indices)
        fields.append(
            {
                "region": name,
                "slot_id": slot.slot_id if slot else None,
                "label": slot.label if slot else name,
                "required": slot.required if slot else False,
                "binding": asdict(binding) if binding else None,
                "status": "error"
                if errors
                else "unbound"
                if not binding
                else "warning"
                if warnings
                else "no-local-error",
                "diagnostic_indices": indices,
            }
        )
    return {
        "schema_version": "inkstruct_template_fit_report_v1",
        "document_id": document.document_id,
        "revision": document.revision,
        "source_sha256": sha256(document.source.encode("utf-8")).hexdigest(),
        "template_sha256": digest(asdict(template)),
        "template_name": template.name,
        "job_key": snapshot.job_key,
        "resource_key": snapshot.resource_key,
        "content_fit_checked": True,
        "exportable": snapshot.exportable,
        "plotter_exportable": snapshot.plotter_exportable,
        "machine_svg_verified": False,
        "physical_alignment_verified": False,
        "pages": len(snapshot.pages),
        "severity_counts": dict(Counter(d.severity for d in snapshot.diagnostics)),
        "fields": fields,
        "diagnostics": diagnostics,
    }


def flow_template_fit(document,flow,snapshot):
    from .named_fields import split_fields
    _,definitions,_=split_fields(document,flow.template)
    fields=[]
    for field in flow.template.fields:
        node=definitions.get(field.field_id)
        indices=[i for i,d in enumerate(snapshot.diagnostics) if getattr(getattr(d,'target',None),'slot_id',None)==field.field_id]
        fields.append({'region':field.field_id,'slot_id':field.field_id,'label':field.label,'required':field.required,
                       'binding':{'node_ids':[node.node_id]} if node else None,
                       'status':'error' if any(snapshot.diagnostics[i].severity=='error' for i in indices) else 'no-local-error' if node else 'unbound',
                       'diagnostic_indices':indices})
    return {'schema_version':'inkstruct_template_fit_report_v2','document_id':document.document_id,
            'revision':document.revision,'source_sha256':sha256(document.source.encode('utf-8')).hexdigest(),
            'template_sha256':digest(asdict(flow.template)),'template_name':flow.template.name,
            'job_key':snapshot.job_key,'resource_key':snapshot.resource_key,'content_fit_checked':True,
            'exportable':snapshot.exportable,'plotter_exportable':snapshot.plotter_exportable,
            'machine_svg_verified':False,'physical_alignment_verified':False,'pages':len(snapshot.pages),
            'page_layouts':[{'page':p.index+1,'layout_id':flow.template.layout(p.index).layout_id,'label':p.source_layout} for p in snapshot.pages],
            'severity_counts':dict(Counter(d.severity for d in snapshot.diagnostics)),
            'fields':fields,'diagnostics':[asdict(d) for d in snapshot.diagnostics]}
