import json
import sqlite3

import pytest

from inkstruct.generation_resources import FrozenStructureRepository, freeze_database
from inkstruct.structures import StructureRepository


def database(path):
    c = sqlite3.connect(path)
    c.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE characters(character TEXT PRIMARY KEY,codepoint INTEGER,graph_json TEXT);')
    c.execute('INSERT INTO metadata VALUES (?,?)', ('source_version', 'one'))
    c.execute('INSERT INTO characters VALUES (?,?,?)', ('孔', ord('孔'), json.dumps({'test': 1})))
    c.commit()
    return c


def test_snapshot_hash_exact_and_committed_wal_changes_are_never_cached_by_path(tmp_path):
    path = tmp_path/'库.sqlite3'
    c = database(path)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA wal_autocheckpoint=0')
    live = StructureRepository(path)
    first = FrozenStructureRepository(path)
    assert first.content_sha256() == live.content_sha256()
    c.execute('UPDATE characters SET graph_json=?', (json.dumps({'test': 2}),))
    c.commit()
    second = FrozenStructureRepository(path)
    assert second.content_sha256() == live.content_sha256() != first.content_sha256()
    assert first._rows['孔'] == json.dumps({'test': 1})
    dest = tmp_path/'backup.sqlite3'
    freeze_database(path, dest)
    assert FrozenStructureRepository(dest).content_sha256() == second.content_sha256()
    c.execute('UPDATE characters SET graph_json=?', (json.dumps({'test': 3}),))
    # Uncommitted data does not leak into a read snapshot or its content identity.
    assert FrozenStructureRepository(path).content_sha256() == second.content_sha256()
    c.rollback()
    c.close()


def test_snapshot_raw_authority_cannot_be_mutated_and_cancel_is_checked(tmp_path):
    path = tmp_path/'one.sqlite3'
    database(path).close()
    view = FrozenStructureRepository(path)
    with pytest.raises(TypeError):
        view._rows['孔'] = '{}'
    metadata = view.metadata();metadata['source_version'] = 'poison'
    assert view.metadata()['source_version'] == 'one'
    with pytest.raises(InterruptedError):
        FrozenStructureRepository(path, lambda: True)
    with pytest.raises(InterruptedError):
        freeze_database(path, tmp_path/'cancel.sqlite3', lambda: True)
