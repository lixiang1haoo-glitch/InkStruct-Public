"""Hashable template diagnostic locations shared by reports and editor navigation."""

from dataclasses import dataclass

from .schema import Diagnostic


@dataclass(frozen=True)
class TemplateTarget:
    region: str
    slot_id: str | None = None
    face: str = "first"
    node_ids: tuple[str, ...] = ()
    anchor: str | None = None
    page_index: int | None = None


@dataclass(frozen=True)
class TemplateDiagnostic(Diagnostic):
    target: TemplateTarget | None = None


def binding_target(template, binding, *, page_index=None, face="first"):
    slot = next((s for s in getattr(template, "slots", ()) if s.region == binding.region), None)
    return TemplateTarget(
        binding.region,
        slot.slot_id if slot else None,
        ("first" if page_index == 0 else "continuation") if page_index is not None else face,
        binding.node_ids,
        binding.anchor,
        page_index,
    )


def with_template_target(diagnostic, target):
    return TemplateDiagnostic(
        diagnostic.code, diagnostic.message, diagnostic.span, diagnostic.severity, target
    )
