"""Local approval of one foreign symbol set for one generated batch."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from .resource_catalog import atomic_json, catalog_write


@dataclass(frozen=True)
class SymbolScope:
    writer: str
    sha256: str
    count: int
    characters: str


@dataclass(frozen=True)
class WriterLink:
    target_writer: str
    batch_sha256: str
    symbols: SymbolScope


class WriterLinkRequired(ValueError):
    def __init__(self, link):
        self.link = link
        super().__init__('标点与汉字批次的书写者 ID 不同，请核对后确认是否为同一人。')


class WriterLinks:
    def __init__(self, workspace):
        self.path = Path(workspace) / 'writer-links.json'
        self.lock_path = self.path.with_suffix('.lock')

    def read(self):
        try:
            data = json.loads(self.path.read_bytes())
        except FileNotFoundError:
            return []
        if (not isinstance(data, dict) or data.get('schema_version') != 'inkstruct_writer_links_v1'
                or not isinstance(data.get('links'), list)
                or any(not isinstance(row, dict) or 'scope' not in row or 'confirmed_at' not in row
                       for row in data['links'])):
            raise ValueError('书写者关联记录格式无效')
        return data['links']

    def allows(self, link):
        return any(row['scope'] == asdict(link) for row in self.read())

    @catalog_write
    def confirm(self, link):
        rows = self.read()
        scope = asdict(link)
        if not any(row['scope'] == scope for row in rows):
            rows.append({'scope': scope, 'confirmed_at': datetime.now(UTC).isoformat()})
            atomic_json(self.path, {'schema_version': 'inkstruct_writer_links_v1', 'links': rows})
