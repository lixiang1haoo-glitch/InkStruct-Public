"""Lossless scalar provenance for parser views of the original source.

Each displayed scalar maps to an original half-open range. Entity expansion can
map several displayed scalars to the same range; a CRLF maps to one parser LF.
No substring search is used to guess the provenance of repeated text.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cancellation import check_cancel
from .schema import SourceSpan


@dataclass(frozen=True)
class MappedText:
    text: str
    ranges: tuple[SourceSpan, ...]

    def __post_init__(self):
        self.text.encode("utf-8")
        object.__setattr__(self, "ranges", tuple(self.ranges))
        if len(self.text) != len(self.ranges):
            raise ValueError("Every displayed scalar must have a source range")
        if any(s.start < 0 or s.end <= s.start for s in self.ranges):
            raise ValueError("Invalid mapped source range")
        if any(a.start > b.start for a, b in zip(self.ranges, self.ranges[1:])):
            raise ValueError("Source mapping must remain in source order")

    @classmethod
    def original(cls, source: str, offset: int = 0) -> MappedText:
        return cls(
            source, tuple(SourceSpan(offset + i, offset + i + 1) for i in range(len(source)))
        )

    def slice(self, start: int, end: int) -> MappedText:
        if not 0 <= start <= end <= len(self.text):
            raise ValueError("Mapped slice outside input")
        return MappedText(self.text[start:end], self.ranges[start:end])

    def covering_span(self, start: int = 0, end: int | None = None) -> SourceSpan:
        end = len(self.text) if end is None else end
        if not 0 <= start < end <= len(self.text):
            raise ValueError("A covering range needs at least one source scalar")
        return SourceSpan(self.ranges[start].start, self.ranges[end - 1].end)

    def replace_segment(self, start: int, end: int, display: str) -> MappedText:
        """Decode a known token, retaining its full original source spelling."""
        span = self.covering_span(start, end)
        return MappedText(
            self.text[:start] + display + self.text[end:],
            self.ranges[:start] + (span,) * len(display) + self.ranges[end:],
        )


def parser_view(source: str, *, cancelled=None) -> MappedText:
    """CommonMark CR/CRLF/NUL normalization with an explicit reverse mapping."""
    source.encode("utf-8")
    text, ranges = [], []
    i = 0
    while i < len(source):
        if i % 256 == 0:
            check_cancel(cancelled)
        start = i
        char = source[i]
        i += 1
        if char == "\r":
            if source[i : i + 1] == "\n":
                i += 1
            char = "\n"
        elif char == "\x00":
            char = "\ufffd"
        text.append(char)
        ranges.append(SourceSpan(start, i))
    check_cancel(cancelled)
    return MappedText("".join(text), tuple(ranges))
