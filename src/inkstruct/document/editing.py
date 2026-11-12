"""Source transactions with stable scalar identities and reversible edits.

Only actual edit ranges create identities; later text retains its IDs even when
its offsets change. AST occurrence IDs can derive from these anchors and role.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .schema import SourceSpan, digest, new_id

IDENTITY_VERSION = "inkstruct_source_identity_v1"
MAX_SCALARS = 100_000


@dataclass(frozen=True)
class Edit:
    start: int
    removed: str
    inserted: str
    removed_ids: tuple[str, ...]
    inserted_ids: tuple[str, ...]


class SourceSession:
    def __init__(self, source: str = "", *, document_id: str | None = None):
        self._validate_source(source)
        self.document_id = document_id or new_id()
        self.source = source
        self.atom_ids = tuple(new_id() for _ in source)
        self.revision = 0
        self._undo: list[Edit] = []
        self._redo: list[Edit] = []

    @staticmethod
    def _validate_source(source):
        source.encode("utf-8")
        if len(source) > MAX_SCALARS:
            raise ValueError("Source exceeds the 100,000 scalar budget")

    def occurrence_id(self, span: SourceSpan, *, role: str, text: str) -> str:
        if not 0 <= span.start < span.end <= len(self.source):
            raise ValueError("Occurrence needs a nonempty source range")
        return digest(
            {
                "version": IDENTITY_VERSION,
                "document": self.document_id,
                "anchors": self.atom_ids[span.start : span.end],
                "role": role,
                "text": text,
            }
        )

    def apply(self, start: int, end: int, inserted: str, *, expected_revision=None, inserted_ids=None) -> Edit:
        if expected_revision is not None and expected_revision != self.revision:
            raise ValueError("Edit belongs to a stale source revision")
        if not (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start <= end <= len(self.source)
        ):
            raise ValueError("Edit range outside source")
        source = self.source[:start] + inserted + self.source[end:]
        self._validate_source(source)
        if inserted_ids is None:
            inserted_ids = tuple(new_id() for _ in inserted)
        else:
            inserted_ids = tuple(inserted_ids)
            if (len(inserted_ids) != len(inserted) or len(set(inserted_ids)) != len(inserted_ids)
                    or set(inserted_ids).intersection(self.atom_ids[:start] + self.atom_ids[end:])):
                raise ValueError("Edit contains invalid or repeated source identities")
        edit = Edit(
            start,
            self.source[start:end],
            inserted,
            self.atom_ids[start:end],
            inserted_ids,
        )
        self.source = source
        self.atom_ids = self.atom_ids[:start] + edit.inserted_ids + self.atom_ids[end:]
        self.revision += 1
        self._undo.append(edit)
        self._undo = self._undo[-128:]
        self._redo.clear()
        return edit

    def undo(self) -> bool:
        if not self._undo:
            return False
        edit = self._undo.pop()
        end = edit.start + len(edit.inserted)
        self.source = self.source[: edit.start] + edit.removed + self.source[end:]
        self.atom_ids = self.atom_ids[: edit.start] + edit.removed_ids + self.atom_ids[end:]
        self.revision += 1
        self._redo.append(edit)
        return True

    def apply_preserving(self, source: str):
        """One reversible dialog transaction, retaining identities of unchanged runs."""
        from difflib import SequenceMatcher
        if source == self.source:
            return None
        self._validate_source(source)
        old, old_ids = self.source, self.atom_ids
        # Prefix/suffix changes are common for field forms; exclude those runs
        # before matching, avoiding quadratic work on long repeated documents.
        prefix=0
        while prefix<min(len(old),len(source)) and old[prefix]==source[prefix]:
            prefix+=1
        suffix=0
        while suffix<min(len(old),len(source))-prefix and old[len(old)-suffix-1]==source[len(source)-suffix-1]:
            suffix+=1
        a=old[prefix:len(old)-suffix if suffix else len(old)]
        b=source[prefix:len(source)-suffix if suffix else len(source)]
        matches=[(0,0,prefix),(len(old)-suffix,len(source)-suffix,suffix)]
        matches.extend((prefix+i,prefix+j,size) for i,j,size in SequenceMatcher(None,a,b,autojunk=max(len(a),len(b))>20_000).get_matching_blocks())
        edit = self.apply(0, len(old), source)
        identities = list(self.atom_ids)
        for a,b,size in matches:
            identities[b:b+size] = old_ids[a:a+size]
        edit = replace(edit, inserted_ids=tuple(identities))
        self.atom_ids = edit.inserted_ids
        self._undo[-1] = edit
        return edit

    def redo(self) -> bool:
        if not self._redo:
            return False
        edit = self._redo.pop()
        end = edit.start + len(edit.removed)
        self.source = self.source[: edit.start] + edit.inserted + self.source[end:]
        self.atom_ids = self.atom_ids[: edit.start] + edit.inserted_ids + self.atom_ids[end:]
        self.revision += 1
        self._undo.append(edit)
        return True

    def identity_record(self) -> dict:
        return {
            "schema_version": IDENTITY_VERSION,
            "document_id": self.document_id,
            "source_digest": digest(self.source),
            "revision": self.revision,
            "atom_ids": list(self.atom_ids),
        }

    @classmethod
    def restore(cls, source: str, record: dict) -> SourceSession:
        if record.get("schema_version") != IDENTITY_VERSION:
            raise ValueError("Unsupported source identity schema")
        if record.get("source_digest") != digest(source):
            raise ValueError("Identity record does not match source")
        ids = tuple(record["atom_ids"])
        revision = record["revision"]
        if (
            len(ids) != len(source)
            or any(not isinstance(i, str) or not i for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("Invalid source identities")
        if (
            not isinstance(revision, int)
            or revision < 0
            or not isinstance(record["document_id"], str)
            or not record["document_id"]
        ):
            raise ValueError("Invalid source identity metadata")
        cls._validate_source(source)
        result = cls("", document_id=record["document_id"])
        result.source = source
        result.atom_ids = ids
        result.revision = revision
        return result
