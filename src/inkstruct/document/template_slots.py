"""Versioned reusable semantic fields; no document identities live in a template."""

from dataclasses import asdict, dataclass, fields
from typing import ClassVar

from .schema import SourceSpan
from .template import PageTemplate, TemplateBinding
from .template_diagnostics import TemplateDiagnostic, TemplateTarget, binding_target
from .template_validation import TemplateValidationError, converted

KINDS = {
    "any": None,
    "text": {"paragraph", "heading"},
    "math": {"math_block"},
    "table": {"table", "html_table"},
}


@dataclass(frozen=True)
class TemplateSlot:
    slot_id: str
    label: str
    region: str
    kind: str = "any"
    required: bool = False
    pages: str = "first"
    scale: float = 1
    anchor: str | None = None

    def __post_init__(self):
        if (
            not isinstance(self.slot_id, str)
            or not 1 <= len(self.slot_id) <= 128
            or not isinstance(self.label, str)
            or not 1 <= len(self.label) <= 256
            or self.kind not in KINDS
            or type(self.required) is not bool
        ):
            raise ValueError("Invalid template slot ID, label, kind or required flag")
        self.bind(("validation-placeholder",))

    def bind(self, node_ids):
        return TemplateBinding(self.region, node_ids, self.pages, self.scale, self.anchor)


@dataclass(frozen=True)
class SlottedPageTemplate(PageTemplate):
    SCHEMA: ClassVar[str] = "inkstruct_page_template_v2"
    schema_version: str = "inkstruct_page_template_v2"
    slots: tuple[TemplateSlot, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.slots, (tuple, list)) or len(self.slots) > 1000:
            raise TemplateValidationError(
                "template-slots-invalid", "Invalid template slot declarations", (("slots",),)
            )
        slots = tuple(converted(s, TemplateSlot, "slots", i) for i, s in enumerate(self.slots))
        if len(slots) > 1000 or any(not isinstance(s, TemplateSlot) for s in slots):
            raise ValueError("Invalid template slot declarations")
        if len({s.slot_id for s in slots}) != len(slots) or len({s.region for s in slots}) != len(
            slots
        ):
            duplicate = next(
                i
                for i, s in enumerate(slots)
                if any(s.slot_id == old.slot_id or s.region == old.region for old in slots[:i])
            )
            current = slots[duplicate]
            paths = tuple(
                ("slots", i)
                for i, s in enumerate(slots)
                if s.slot_id == current.slot_id or s.region == current.region
            )
            raise TemplateValidationError(
                "template-slots-duplicate", "Template slots require unique IDs and regions", paths
            )
        for i, slot in enumerate(slots):
            for face in (self.first, self.continuation) if slot.pages == "all" else (self.first,):
                if not any(r.name == slot.region for r in face.reserved):
                    raise TemplateValidationError(
                        "template-slot-region-missing",
                        f"Slot {slot.slot_id}: target region is missing",
                        (("slots", i, "region"),),
                    )
                if slot.anchor and not any(a.name == slot.anchor for a in face.anchors):
                    raise TemplateValidationError(
                        "template-slot-anchor-missing",
                        f"Slot {slot.slot_id}: baseline anchor is missing",
                        (("slots", i, "anchor"),),
                    )
        object.__setattr__(self, "slots", slots)


def upgrade_template(template):
    if isinstance(template, SlottedPageTemplate):
        return template
    return SlottedPageTemplate(**{**asdict(template), "schema_version": SlottedPageTemplate.SCHEMA})


def geometry_only(template):
    """Internal rendering view; never used to save or silently downgrade a design."""
    if not isinstance(template, SlottedPageTemplate):
        return template
    data = {f.name: getattr(template, f.name) for f in fields(PageTemplate)}
    return PageTemplate(**{**data, "schema_version": PageTemplate.SCHEMA})


def slot_diagnostics(document, template, bindings):
    by_region = {b.region: b for b in bindings}
    nodes = {n.node_id: n for n in document.nodes}
    issues = []
    for slot in getattr(template, "slots", ()):
        binding = by_region.get(slot.region)
        span = SourceSpan(0, 0)
        code, message = None, ""
        if binding is None:
            if slot.required:
                code, message = "template-slot-required", "required field has no content binding"
        else:
            selected = [n for n in document.nodes if n.node_id in binding.node_ids]
            if selected:
                span = SourceSpan(selected[0].span.start, selected[-1].span.end)
            if binding != slot.bind(binding.node_ids):
                code, message = (
                    "template-slot-policy",
                    "binding disagrees with the template field policy",
                )
            elif KINDS[slot.kind] is not None and any(
                nodes[i].kind not in KINDS[slot.kind] for i in binding.node_ids if i in nodes
            ):
                code, message = "template-slot-kind", f"field requires {slot.kind} blocks"
        if code:
            target = (
                binding_target(template, binding)
                if binding
                else TemplateTarget(slot.region, slot.slot_id, anchor=slot.anchor)
            )
            issues.append(
                TemplateDiagnostic(
                    code, f"Slot {slot.slot_id} ({slot.label}): {message}", span, target=target
                )
            )
    return tuple(issues)
