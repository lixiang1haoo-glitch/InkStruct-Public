"""Actual sample import -> profile -> both engines -> font -> frozen layout."""
import argparse
import gzip
import json
from dataclasses import asdict
from pathlib import Path

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage, decode, to_user
from inkstruct.fonts.importer import build_font
from inkstruct.generation_workflow import GenerationWorkflow, read, write
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan


def verify_flow(service, writer, samples, method, text, out):
    print(method, 'import', flush=True)
    imported = service.import_samples(writer, str(samples), method)
    print(imported, flush=True)
    built = service.build_profile(writer, str(samples), method)
    print(built, flush=True)
    generated = service.generate(writer, str(samples), method, text, progress=lambda r: print(r, flush=True))
    assert generated['completed_count'] == len(set(text)) and generated['failed_count'] == 0, generated
    run = Path(generated['output'])
    dev = out / (method + '-developer.inkfont')
    user = out / (method + '.inkfont')
    build_font(dev, writer=writer, name='generation acceptance ' + method, run=run)
    to_user(dev, user)
    a, b = FontPackage(dev), FontPackage(user)
    assert a.records == b.records and a.manifest['core_hash'] == b.manifest['core_hash']
    originals = {}
    if method == 'v61':
        protocol = read(run/'protocol.json')
        for c in protocol['characters']:
            originals[c] = json.loads(gzip.decompress((run/writer/f'{ord(c):04X}.json.gz').read_bytes()))['glyph']
    else:
        originals = {r['character']: r for r in map(read, (run/'trajectories').glob('*.json'))}
    for asset in b.glyphs():
        record = decode(asset.original_json)
        original = originals[asset.character]
        assert [s['points'] for s in record['trajectory']['strokes']] == [s['points'] for s in original['strokes']]
        assert record['summary']['generation_method'] == ('v6.1 exp' if method == 'v61' else 'v4 adaptive')
    session = SourceSession(text)
    resolver = AssetResolver(embedded=b.glyphs())
    before = layout_markdown(parse_markdown(session), resolver)
    assert before.plotter_exportable, before.diagnostics
    warnings = resolver.usage_warnings()
    resolver.accept_usage_warnings()
    before = layout_markdown(parse_markdown(session), resolver)
    doc = out / (method + '.inkdoc')
    save_package(doc, session, resolver, PageProfile(), StyleProfile())
    reopened = load_package(doc)
    after = layout_markdown(parse_markdown(reopened.session), reopened.resolver)
    assert asdict(before) == asdict(after)
    assert reopened.resolver.selection_records() == resolver.selection_records()
    export_plan(plan_from_snapshot(after), out / (method + '-svg'), optimize=True)
    return {'import': imported, 'profile': built, 'generation': generated, 'font': b.verify(),
            'warnings': warnings, 'core_identity_equal': True, 'all_points_pressure_time_exact': True,
            'document_frozen_exact': True, 'source_kinds': {c: read(run/writer/f'{ord(c):04X}.json')['source_kinds'] for c in text} if method=='v61' else {}}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--samples',type=Path,required=True)
    parser.add_argument('--writer',default='scx')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--text',default='人物理羚而铜伯')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    service=GenerationWorkflow(args.output/'workspace',Path('artifacts/structures/characters.sqlite3'))
    reports={}
    for method in ('v61','v4'):
        reports[method]=verify_flow(service,args.writer,args.samples.resolve(),method,args.text,args.output)
        write(args.output/'verification.json',reports)
    print('PASS',flush=True)


if __name__=='__main__':main()
