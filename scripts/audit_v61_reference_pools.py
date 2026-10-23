"""Read-only audit of frozen v6.1 pool exclusions; never admits new instances."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from run_v6_exp import sha, write
from run_v61_exp import WRITERS
from run_v61_reference_exp import ARCHIVES, PRIOR

from inkstruct.component_views import expand_views
from inkstruct.exemplar_index import component_key
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.v6_exp import NESTED_COMPONENTS
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_reference_exp import ReferenceAblationGenerator


def run(root):
    out = root / 'pool_audit.json'
    if out.exists():
        raise FileExistsError(out)
    base = StructureRepository(Path('artifacts/full_library_20261010/inputs/characters.sqlite3'))
    target = CorrectedStructureRepository(base,Path('third_party/makemeahanzi/graphics.txt'),
        Path('third_party/makemeahanzi/dictionary.txt'),Path('configs/structure_overrides/unclipped_reference_v1.json'))
    results = []
    for writer in WRITERS:
        engine = ReferenceAblationGenerator(load_profile(ARCHIVES/writer/'source_archive.json'),base,target)
        records = json.loads((root/writer/'records.json').read_text())
        for r in records:
            c = r['character']
            original = target.get(c)
            graph = framed_graph(expand_views(original,target,allowed=NESTED_COMPONENTS).graph,
                                 reference_frame(original))
            for cov in r['coverage']:
                cid = cov['component_id']
                node = next(n for n in graph.components if n.component_id==cid)
                key = component_key(graph,node)
                raw = [x for x in engine.v6.index.by_key.get(key,[]) if x['character']!=c]
                eligible = engine.v6.index.candidates(graph,node)
                frozen = r['pool'][cid]
                assert len(frozen)==min(len(eligible),16)
                assert [x['candidate'] for x in frozen]==eligible[:16]
                identity = lambda p:(p['sample_id'],p['component_id'])
                accepted = {identity(x) for x in eligible}
                rejected=[]
                for p in raw:
                    if identity(p) not in accepted:
                        # In this index, equal context entries are excluded only by shape/aspect gates.
                        rejected.append({'candidate':p,'reason':'reference shape > .18 or log aspect > .7'})
                reason = ('accepted author component' if cov['baseline_donor'] else
                    'eligible pool but placement guard rejected' if frozen else
                    'reference shape/aspect filter removed all' if raw else
                    'no same identity/variant/role/parent-layout/count indexed instance')
                results.append({'writer':writer,'character':c,**cov,'context_key':key,
                    'same_context_indexed':len(raw),'eligible_before_top16':len(eligible),
                    'reference_filter_rejected':rejected,'diagnosis':reason})
    counts=Counter(r['diagnosis'] for r in results)
    write(out,{'script_sha256':sha(Path(__file__)), 'protocol_sha256':sha(root/'protocol.json'),
        'source_prior':str(PRIOR),'mutated_sources':False,'totals':dict(counts),'components':results})
    print(dict(counts))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    run(p.parse_args().run)
