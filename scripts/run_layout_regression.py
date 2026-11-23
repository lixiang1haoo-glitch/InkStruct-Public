"""Run integrated layout tests with private settings, including spawn children."""
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    private=ROOT/'artifacts'/('layout-regression-'+uuid4().hex)
    support=private/'test-support';support.mkdir(parents=True,exist_ok=False)
    temporary=private/'temp';temporary.mkdir(exist_ok=False)
    os.environ.update(TEMP=str(temporary),TMP=str(temporary),TMPDIR=str(temporary))
    import tempfile
    tempfile.tempdir=str(temporary)
    os.environ.update(QT_QPA_PLATFORM='offscreen',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
        INKSTRUCT_LAYOUT_PREVIEW_HOME=str(private/'settings'))
    code=('import os\nfrom inkstruct_layout_launcher import configure_preview\n'
          'configure_preview()\nos.environ.pop("INKSTRUCT_LAYOUT_PREVIEW",None)\n')
    (support/'sitecustomize.py').write_text(code,encoding='utf8')
    os.environ['PYTHONPATH']=os.pathsep.join(map(str,[support,ROOT,ROOT/'src',ROOT/'packaging']))
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')
    sys.path[:0]=list(map(str,[ROOT,ROOT/'src',ROOT/'packaging']))
    exec(compile(code,str(support/'sitecustomize.py'),'exec'),{})
    import pytest
    patterns=['test_math*.py','test_compact_math*.py','test_fraction_default.py','test_equation_numbers.py',
        'test_symbol*.py','test_hbar_symbols.py','test_shared_punctuation.py','test_punctuation*.py','test_font*.py',
        'test_recorded_math_symbols.py','test_document_resources.py','test_document_package.py','test_source_identity.py',
        'test_measurement_cache.py','test_preview_serialization.py','test_table_export.py','test_break_commands.py',
        'test_markdown*.py','test_obsidian*.py','test_flow_templates.py','test_flow_template_qt.py',
        'test_continuation*.py','test_suffix_continuation.py','test_footnote*.py','test_mixed_tables.py','test_plain_content_mode.py',
        'test_parse_cancellation.py','test_template_fields.py','test_template_slots.py','test_templates.py',
        'test_capture_management.py','test_generation_targets.py','test_generation_workflow.py','test_generation_parallel.py','test_generation_variants.py',
        'test_character_sets.py','test_character_sets_qt.py','test_parallel_export.py','test_background_export_qt.py',
        'test_resource_management_qt.py','test_integrated_window_qt.py',
        'test_workspace_modes_qt.py','test_inspector_context_qt.py',
        'test_natural_variation.py','test_layout_problems*.py','test_justification_han*.py',
        'test_glyph_corrections*.py','test_global_defaults.py','test_unified_settings_qt.py',
        'test_settings_usability_qt.py','test_latin_spacing.py','test_force_svg*.py',
        'test_settings_template_preservation*.py','test_svg_export*.py',
        'test_missing_raster_export*.py','test_raster_export*.py','test_template_partial_preview*.py']
    paths=sorted({str(p) for pattern in patterns for p in (ROOT/'tests').glob(pattern)})
    options=sys.argv[1:]
    if not any(a=='--basetemp' or a.startswith('--basetemp=') for a in options):options=[*options,'--basetemp='+str(private/'tmp')]
    print(f'Private integrated regression: {len(paths)} files; settings {private}',flush=True)
    return pytest.main([*paths,'-p','no:cacheprovider',*options])


if __name__=='__main__':raise SystemExit(main())
