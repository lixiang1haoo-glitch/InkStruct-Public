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


def template_record(template, record=None):
    if template is None:
        return None
    data = asdict(template) if record is None else record
    data.pop('revision', None)
    revision = template.revision
    if revision is not None and revision.content_hash == digest(data):
        return {'schema_version': SCHEMA, 'revision': asdict(revision), 'template': data}
    return data


def template_revision(template):
    """An unchanged legacy snapshot has a deterministic identity by content."""
    record = template_record(template)
    if record['schema_version'] == SCHEMA:
        return template.revision
    key = digest(record)
    return TemplateRevision(str(uuid5(NAMESPACE_URL, 'inkstruct:template:' + key)),
                            str(uuid5(NAMESPACE_URL, 'inkstruct:revision:' + key)),
                            None, 1, key)


def version_template(template, *, parent=None):
    data = asdict(template)
    data.pop('revision', None)
    content_hash = digest(data)
    if parent is None:
        revision = TemplateRevision(str(uuid4()), str(uuid4()), None, 1, content_hash)
    else:
        prior = template_revision(parent)
        if prior.content_hash == content_hash:
            raise ValueError("模板内容没有变化，未创建新修订")
        revision = TemplateRevision(prior.template_id, str(uuid4()), prior.revision_id,
                                    prior.number + 1, content_hash)
    return replace(template, revision=revision)
