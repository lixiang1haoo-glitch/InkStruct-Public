"""Indexed Han choices for a previously verified font release."""

from contextlib import contextmanager
from dataclasses import dataclass
from zipfile import BadZipFile, ZipFile

from ..document.cancellation import check_cancel
from .core import decode, resolved_candidate
from .library import fingerprint


class PreviewFontError(RuntimeError):
    """Abort the build instead of reporting damaged data as a missing glyph."""


@dataclass(frozen=True, eq=False)
class IndexedCandidate:
    sample_id: str
    metrics_key: str
    font_metadata: dict


class PreviewCandidates:
    def __init__(self, font, characters, cache, cancelled):
        self.font = font
        self.token = font.preview_token
        self.cache = cache
        self.cancelled = cancelled
        self.archive = None
        self.pools = {}
        for character in sorted(characters):
            check_cancel(cancelled)
            if records := font.pools.get(character):
                self.pools[character] = tuple(
                    IndexedCandidate(record["candidate_id"], record["metrics_id"], {
                        "identity": font.identity, "record": record,
                        "summary": font.provenance[record["candidate_id"]],
                    }) for record in records
                )

    def check_file(self):
        try:
            stamp = fingerprint(self.font.path)
        except OSError as error:
            raise PreviewFontError("无法读取原字体文件，请重新连接字体") from error
        if stamp != self.token[1]:
            raise PreviewFontError("字体文件已变化，请重新导入")

    @contextmanager
    def opened(self):
        self.check_file()
        try:
            archive = ZipFile(self.font.path)
        except (OSError, BadZipFile) as error:
            raise PreviewFontError(f"无法打开原字体文件：{error}") from error
        with archive:
            self.archive = archive
            try:
                yield
                self.check_file()
            finally:
                self.archive = None

    def load(self, candidate):
        key = self.token, candidate.sample_id
        glyph = self.cache.get(key) if self.cache is not None else None
        if glyph is not None:
            return glyph
        if self.archive is None:
            with self.opened():
                return self.load(candidate)
        check_cancel(self.cancelled)
        metadata = candidate.font_metadata
        record = metadata["record"]
        try:
            trajectory = decode(self.font._checked(self.archive, record["file"]))
            glyph = resolved_candidate(record, trajectory, self.font.metrics[candidate.sample_id],
                                       metadata["summary"], self.font.identity)
        except (OSError, ValueError, TypeError, KeyError, BadZipFile) as error:
            raise PreviewFontError(f"字体轨迹不可读取：{record['character']} · {error}") from error
        object.__setattr__(glyph, "_preview_font_token", self.token)
        if self.cache is not None:
            self.cache.put((key,), glyph, glyph.retained_bytes)
        return glyph
