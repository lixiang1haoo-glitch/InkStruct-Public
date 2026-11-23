"""Portable content revision identity, separate from the layout grammar."""

from dataclasses import asdict, dataclass, replace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .schema import digest

SCHEMA = "inkstruct_template_revision_v1"


@dataclass(frozen=True)
class TemplateRevision:
    template_id: str
    revision_id: str
    parent_id: str | None
    number: int
    content_hash: str

    def __post_init__(self):
        ids = (self.template_id, self.revision_id)
        if self.parent_id is not None:
            ids += (self.parent_id,)
        try:
            if any(not isinstance(key, str) or str(UUID(key)) != key for key in ids):
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ValueError("无效模板修订身份") from None
        if (type(self.number) is not int or not 1 <= self.number <= 1_000_000
                or (self.parent_id is None) != (self.number == 1)
                or self.parent_id in (self.template_id, self.revision_id)
                or not isinstance(self.content_hash, str) or len(self.content_hash) != 64
                or any(char not in '0123456789abcdef' for char in self.content_hash)):
            raise ValueError("无效模板修订关系")


def _content_record(template, record=None):
    data = asdict(template) if record is None else record
    data.pop('revision', None)
    data.pop('paper_origins', None)
    if not data.get('family_id'):
        data.pop('family_id', None)
    # Omit the new optional property from legacy records to preserve their hashes.
    if data.get('schema_version') == 'inkstruct_page_template_v3':
        if data.get('plotter_alignment') is None:
            data.pop('plotter_alignment', None)
        for layout in data.get('layouts', ()):
            if layout.get('plotter_alignment') is None:
                layout.pop('plotter_alignment', None)
            for frame in layout['frames']:
                if frame.get('paper_grid') is None:
                    frame.pop('paper_grid', None)
    return data


def template_record(template, record=None):
    if template is None:
        return None
    data = _content_record(template, record)
    revision = template.revision
    old_hash = digest(data)
    data.pop('plotter_alignment', None)
    for layout in data.get('layouts', ()):
        layout.pop('plotter_alignment', None)
    clean_hash = digest(data)
    if revision is not None and revision.content_hash in (old_hash, clean_hash):
        if clean_hash != revision.content_hash:
            revision = TemplateRevision(revision.template_id, str(uuid5(UUID(revision.revision_id), clean_hash)),
                                        revision.revision_id, revision.number + 1, clean_hash)
        data = {'schema_version': SCHEMA, 'revision': asdict(revision), 'template': data}
    return data


def template_revision(template):
    """An unchanged legacy snapshot has a deterministic identity by content."""
    record = template_record(template)
    if record['schema_version'] == SCHEMA:
        return TemplateRevision(**record['revision'])
    key = digest(_content_record(template))
    family = getattr(template, 'family_id', '')
    return TemplateRevision(str(UUID(hex=family) if family else uuid5(NAMESPACE_URL, 'inkstruct:template:' + key)),
                            str(uuid5(NAMESPACE_URL, 'inkstruct:revision:' + key)),
                            None, 1, key)


def version_template(template, *, parent=None):
    data = template_record(replace(template, revision=None))
    content_hash = digest(data)
    if parent is None:
        revision = TemplateRevision(str(uuid4()), str(uuid4()), None, 1, content_hash)
    else:
        prior = template_revision(parent)
        if prior.content_hash == content_hash:
            if getattr(template, 'paper_origins', ()) != getattr(parent, 'paper_origins', ()):
                return replace(template, revision=parent.revision)
            raise ValueError("模板内容没有变化，未创建新修订")
        revision = TemplateRevision(prior.template_id, str(uuid4()), prior.revision_id,
                                    prior.number + 1, content_hash)
    return replace(template, revision=revision)
