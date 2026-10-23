from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from inkstruct.collection_receipt import extract_new_batch, partition_samples


def sample(c, key):
    return SimpleNamespace(character=c, sample_id=key, source_sha256=key)


def test_all_repeats_follow_frozen_character_group():
    rows = [sample('请','a'), sample('铜','b'), sample('铜','c'), sample('外','d')]
    result = partition_samples(rows, {'请'}, {'铜'})
    assert [s.sample_id for s in result['training']] == ['a']
    assert [s.sample_id for s in result['evaluation']] == ['b','c']
    assert [s.sample_id for s in result['unplanned']] == ['d']
    with pytest.raises(ValueError, match='overlap'):
        partition_samples(rows, {'铜'}, {'铜'})
    with pytest.raises(ValueError, match='duplicate'):
        partition_samples([sample('请','a'), sample('请','a')], {'请'}, set())


def test_zip_preflight_prevents_partial_or_overwriting_extraction(tmp_path):
    archive = tmp_path/'bad.zip'
    with ZipFile(archive,'w') as z:
        z.writestr('user/a.json','{}')
        z.writestr('../escape.json','{}')
    output = tmp_path/'received'
    with pytest.raises(ValueError, match='unsafe'):
        extract_new_batch(archive,output)
    assert not output.exists()
    good = tmp_path/'good.zip'
    with ZipFile(good,'w') as z:
        z.writestr('user/a.json','{"raw":true}')
    paths = extract_new_batch(good,output)
    assert paths[0].read_bytes() == b'{"raw":true}'
    with pytest.raises(FileExistsError):
        extract_new_batch(good,output)
