"""Repeated problems are grouped, while every source target remains available."""
from inkstruct.document.schema import Diagnostic, SourceSpan
from inkstruct.editor.problem_details import group_issues


def test_missing_characters_group_by_character_without_dropping_positions():
    source='汉汉文汉'
    diagnostics=tuple(Diagnostic('asset-missing',f"Missing glyph resource: '{char}'",SourceSpan(i,i+1)) for i,char in enumerate(source))
    groups=group_issues(diagnostics,source)
    assert len(groups)==2
    assert groups[0].title=='缺少字形「汉」'
    assert [d.span.start for d in groups[0].diagnostics]==[0,1,3]
    assert '字体' in groups[0].suggestion


def test_stop_error_precedes_warnings_and_raw_details_stay_intact():
    diagnostics=(Diagnostic('image-reference','Raw image details',SourceSpan(1,2),'warning'),
                 Diagnostic('template-body-no-progress','Raw stop details',SourceSpan(3,5)),
                 Diagnostic('math-command-unsupported','Unknown command: \bad',SourceSpan(6,10)))
    groups=group_issues(diagnostics,'abcdefghijk')
    assert groups[0].title=='正文流在此停止'
    assert groups[-1].severity=='warning'
    assert groups[0].diagnostics[0] is diagnostics[1]
    assert any('公式' in group.title for group in groups)


def test_math_placeholder_is_attached_to_its_cause_without_losing_raw_details():
    cause=Diagnostic('math-command-unsupported','Unknown command',SourceSpan(2,7))
    placeholder=Diagnostic('unsupported-inline','Unsupported placeholder',SourceSpan(1,10))
    unrelated=Diagnostic('unsupported-inline','Other unsupported content',SourceSpan(12,15))
    groups=group_issues((cause,placeholder,unrelated),'x'*20)
    assert len(groups)==2
    assert groups[0].diagnostics==(cause,) and groups[0].related==(placeholder,)
    assert groups[1].diagnostics==(unrelated,)


def test_matching_source_spans_in_different_template_fields_are_not_merged():
    from inkstruct.document.template_diagnostics import TemplateDiagnostic, TemplateTarget
    cause=TemplateDiagnostic('math-command-unsupported','Unknown command',SourceSpan(2,7),target=TemplateTarget('header'))
    other=TemplateDiagnostic('unsupported-inline','Unrelated content',SourceSpan(1,10),target=TemplateTarget('body'))
    groups=group_issues((cause,other),'x'*20)
    assert len(groups)==2 and all(not group.related for group in groups)
