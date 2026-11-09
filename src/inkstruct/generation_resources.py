"""Task-local immutable structure view. Never cache identities of a live database."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import MappingProxyType

from .structures import graph_from_dict


class FrozenStructureRepository:
    """Read all rows in ONE SQLite transaction, including committed WAL data.

    Private immutable strings are the authority for get/iteration AND identity.
    Returned graphs are freshly decoded, so an engine cannot poison this view.
    A new task always constructs a new view; no path/mtime identity cache exists.
    """

    def __init__(self, path, cancelled=lambda: False):
        self.path = Path(path)
        rows = {}
        with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            connection.execute('BEGIN')
            metadata = dict(connection.execute('SELECT key, value FROM metadata'))
            for character, raw in connection.execute('SELECT character, graph_json FROM characters ORDER BY codepoint'):
                if cancelled():
                    raise InterruptedError('生成已取消')
                rows[character] = raw
        self._rows = MappingProxyType(rows)
        self._metadata = MappingProxyType(metadata)
        digest = hashlib.sha256()
        identity = {key: metadata.get(key) for key in (
            'schema_version', 'source', 'source_version', 'coordinate_space', 'component_schema')}
        digest.update(json.dumps(identity, sort_keys=True).encode())
        for character, raw in rows.items():
            if cancelled():
                raise InterruptedError('生成已取消')
            digest.update(json.dumps([character, json.loads(raw)], sort_keys=True, separators=(',', ':')).encode())
            digest.update(b'\n')
        self._digest = digest.hexdigest()

    def get(self, character):
        if character not in self._rows:
            raise KeyError(f'unsupported character: {character}')
        return graph_from_dict(json.loads(self._rows[character]))

    def characters(self):
        return list(self._rows)

    def iter_graphs(self):
        for raw in self._rows.values():
            yield graph_from_dict(json.loads(raw))

    def metadata(self):
        return dict(self._metadata)

    def count(self):
        return len(self._rows)

    def content_sha256(self):
        return self._digest


def freeze_database(source, destination, cancelled=lambda: False):
    """SQLite backup preserves a consistent committed view, not just the main file."""
    def progress(*_):
        if cancelled():
            raise InterruptedError('生成已取消')
    with sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst, pages=256, progress=progress)
