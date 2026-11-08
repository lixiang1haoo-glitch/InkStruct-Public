"""Global parameter application preserves document-owned templates unless explicit."""
from dataclasses import replace

from test_flow_templates import template
from test_templates import template as legacy_template

from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import TemplateBinding
from inkstruct.global_defaults import LayoutDefaults, document_flow


def test_parameter_defaults_preserve_custom_template_and_document_state():
    current_template=template()
    default_template=replace(template(),name='global-default',width_mm=130)
    current=FlowStyle(template=current_template)
    defaults=LayoutDefaults(flow=FlowStyle(template=default_template,paragraph_gap_mm=7))
    changed=document_flow(defaults,current)
    assert changed.template is current_template and changed.paragraph_gap_mm==7
    explicit=document_flow(defaults,current,apply_template=True)
    assert explicit.template is default_template


def test_legacy_bindings_survive_parameter_changes_but_not_explicit_template_replacement():
    original=legacy_template()
    bindings=(TemplateBinding('header',('node-1',)),)
    current=FlowStyle(template=original,template_bindings=bindings)
    defaults=LayoutDefaults(flow=FlowStyle())
    changed=document_flow(defaults,current)
    assert changed.template is original and changed.template_bindings==bindings
    explicit=document_flow(defaults,current,apply_template=True)
    assert explicit.template is None and not explicit.template_bindings
