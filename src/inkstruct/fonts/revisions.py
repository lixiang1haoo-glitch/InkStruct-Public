"""Publish scoped regenerated candidates while keeping all other font data exact."""
from __future__ import annotations

import copy
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

from .core import (
    FontPackage,
    encoded,
    semantic_hash,
    trajectory_hashes,
    validate_candidate,
    write_archive,
)
from .importer import generated_records, make_generated
from .parallel_verify import verify_font


def replace_generated(source, run, output, *, writer, characters, name, font_version,
                      progress=lambda _: None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    requested = set(characters)
    if not requested or not name or not font_version:
        raise ValueError('explicit characters, name and font version required')
    font = FontPackage(source, verify_all=False)
    verify_font(font, progress=progress)
    if font.manifest['writer_alias'] != writer:
        raise ValueError('writer differs from source font')
    replacements = {}
    for glyph, row, payload, protocol in generated_records(run, writer):
        if glyph['character'] in requested:
            if glyph['character'] in replacements or row is None:
                raise ValueError('replacement identity ambiguous')
            replacements[glyph['character']] = (*make_generated(glyph, row, payload, protocol), protocol)
    if set(replacements) != requested:
        raise ValueError('requested regeneration incomplete')
    targets = [r for r in font.records if r['character'] in requested
               and font.provenance[r['candidate_id']]['source_kind'] == 'generated']
    if {r['character'] for r in targets} != requested:
        raise ValueError('source font lacks requested generated candidates')
    if any(sum(r['character'] == c for r in targets) != 1 for c in requested):
        raise ValueError('multiple generated samples require an explicit candidate selection')
    manifest = {k: v for k, v in font.manifest.items()
                if k not in ('members', 'content_hash', 'core_hash', 'core_members')}
    manifest.update(release_id=str(uuid.uuid4()), package_id=str(uuid.uuid4()),
        name=name, font_version=font_version,
        derived_from_package={'package_id': font.manifest['package_id'],
                              'content_hash': font.manifest['content_hash']})
    index, metrics, provenance = map(copy.deepcopy, (font.index, font.metrics, font.provenance))
    changed = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as folder, zipfile.ZipFile(font.path) as z:
        members = {}
        for i, member in enumerate(font.manifest['members']):
            path = Path(folder)/str(i)
            path.write_bytes(font._checked(z, member))
            members[member] = path
        for old in targets:
            trajectory, m, summary, protocol = replacements[old['character']]
            summary = copy.deepcopy(summary)
            summary['regeneration_revision'] = {
                'source_package': font.manifest['package_id'], 'source_candidate': old['candidate_id'],
                'source_trajectory_hash': old['trajectory_hash'],
                'method': protocol['method'], 'rule': protocol.get('semantic_admission'),
                'scope': 'explicit generated candidates; recorded samples and all other candidates retained'}
            cid = str(uuid.uuid4())
            hashes = trajectory_hashes(trajectory)
            record = {**old, 'candidate_id': cid, **hashes,
                'file': 'glyphs/'+hashes['trajectory_hash']+'.json',
                'metrics_id': semantic_hash(m), 'source_summary_hash': semantic_hash(summary)}
            validate_candidate(record, trajectory, m, summary)
            metrics.pop(old['candidate_id']); provenance.pop(old['candidate_id'])
            metrics[cid], provenance[cid] = m, summary
            index['candidates'][font.records.index(old)] = record
            members[record['file']] = encoded(trajectory)
            changed.append({'character': old['character'], 'old_candidate': old['candidate_id'],
                            'new_candidate': cid, 'reference_strokes': summary['reference_strokes']})
        members.update({'index.json': encoded(index), 'metrics.json': encoded(metrics),
                        'provenance.json': encoded(provenance)})
        if font.fingerprint != (font.path.stat().st_size, font.path.stat().st_mtime_ns):
            raise ValueError('source font changed during revision')
        staged = Path(folder)/'revised.inkfont'
        write_archive(staged, members, manifest)
        revised = FontPackage(staged, verify_all=False)
        stats = verify_font(revised, progress=progress)
        # Atomic no-overwrite publication, after complete verification.
        os.link(staged, output)
    return {'font': str(output), 'statistics': stats, 'changed': changed,
            'source_identity': font.identity, 'identity': revised.identity}
