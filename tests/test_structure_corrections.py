import json
from dataclasses import asdict

import numpy as np
import pytest

from inkstruct.samples import sha256_file
from inkstruct.structure_corrections import (
    POLICY,
    CorrectedStructureRepository,
    propose_sparse_strip,
)
from inkstruct.structure_defects import audit_stroke
from inkstruct.structures import StructureRepository, build_database


def fixture_repository(tmp_path):
    graphics, dictionary, database, config = [tmp_path / n for n in ('graphics', 'dictionary', 'db', 'config')]
    graphics.write_text(json.dumps({'character': '一', 'strokes': ['M 0 20 L 100 20 L 100 -40 L 0 -40 Z'], 'medians': [[[10, 10], [90, -20]]]})+'\n')
    dictionary.write_text(json.dumps({'character': '一', 'decomposition': '一', 'matches': [[]]})+'\n')
    build_database(graphics, dictionary, database, source_version='fixture')
    base = StructureRepository(database)
    config.write_text(json.dumps({'policy': POLICY, 'graphics_sha256': sha256_file(graphics), 'dictionary_sha256': sha256_file(dictionary), 'database_content_sha256': base.content_sha256(), 'outline_repairs': []}))
    return base, graphics, dictionary, config


def test_unclipping_preserves_source_identity_and_base(tmp_path):
    base, graphics, dictionary, config = fixture_repository(tmp_path)
    before = asdict(base.get('一'))
    corrected = CorrectedStructureRepository(base, graphics, dictionary, config)
    graph = corrected.get('一')
    assert graph.strokes[0].median == [(10/1024, 1-10/1024), (90/1024, 1+20/1024)]
    assert graph.strokes[0].stroke_id == 's1' and graph.strokes[0].order == 1
    assert asdict(base.get('一')) == before
    graph.strokes[0].median[0] = (999, 999)
    assert corrected.get('一').strokes[0].median[0] == (10/1024, 1-10/1024)
    assert corrected.events['一']['changes'][0]['changed_vertices'] == 1


def test_identity_mismatch_rejects(tmp_path):
    base, graphics, dictionary, config = fixture_repository(tmp_path)
    graphics.write_text(graphics.read_text()+'\n')
    with pytest.raises(ValueError, match='hash mismatch'):
        CorrectedStructureRepository(base, graphics, dictionary, config)


def test_sparse_strip_preserves_anchors_and_bends():
    outline = 'M 0 -10 L 50 20 L 100 -10 L 100 10 L 50 40 L 0 10 Z'
    points, report = propose_sparse_strip(outline, [[5, 3], [95, 3]])
    assert points[0] == [5, 3] and points[-1] == [95, 3]
    assert np.max(np.asarray(points)[:, 1]) > 25
    assert report['sampled_outside_max'] <= 1


def test_complex_cross_sections_rejected():
    outline = 'M 0 0 L 100 0 L 100 100 L 0 100 L 0 80 L 80 80 L 80 20 L 0 20 Z'
    with pytest.raises(ValueError, match='cross sections'):
        propose_sparse_strip(outline, [[10, 10], [70, 90]])


def test_outside_anchors_rejected():
    with pytest.raises(ValueError, match='anchors'):
        propose_sparse_strip('M 0 0 L 100 0 L 100 20 L 0 20 Z', [[5, 50], [95, 50]])


def test_clipping_is_separate_from_outline_suspicions():
    row = audit_stroke('M 0 20 L 100 20 L 100 -40 L 0 -40 Z', [[10, 10], [90, -20]])
    assert row['confirmed'] == ['import_clipping']
    assert 'outside_own_outline' not in row['suspected']
    outside = audit_stroke('M 0 0 L 100 0 L 100 20 L 0 20 Z', [[10, 50], [90, 50]])
    assert 'outside_own_outline' in outside['suspected']
