"""Conservative text segmentation, not a claim of full UAX 14/29 conformance.

Unsupported scripts/clusters remain intact and are diagnosed by the provider.
Original CR, LF and CRLF sequences are never normalized.
"""

from __future__ import annotations

import unicodedata

from .schema import Document, Node, Occurrence, PageProfile, SourceSpan, StyleProfile, new_id

SEGMENTATION_VERSION = "conservative-clusters-v1/" + unicodedata.unidata_version


def scalar_to_utf16(source: str, offset: int) -> int:
    if not 0 <= offset <= len(source):
        raise ValueError("Scalar offset outside source")
    return len(source[:offset].encode("utf-16-le")) // 2


def utf16_to_scalar(source: str, offset: int) -> int:
    if offset < 0:
        raise ValueError("UTF-16 offset outside source")
    position = 0
    for index, char in enumerate(source):
        if position == offset:
            return index
        position += 2 if ord(char) > 0xFFFF else 1
        if position > offset:
            raise ValueError("UTF-16 offset splits a surrogate pair")
    if position == offset:
        return len(source)
    raise ValueError("UTF-16 offset outside source")


def clusters(source: str):
    index = 0
    while index < len(source):
        start = index
        char = source[index]
        index += 1
        if char == "\r" and source[index : index + 1] == "\n":
            index += 1
        elif char not in "\r\n":
            if (
                0x1F1E6 <= ord(char) <= 0x1F1FF
                and index < len(source)
                and 0x1F1E6 <= ord(source[index]) <= 0x1F1FF
            ):
                index += 1
            while index < len(source):
                cp = ord(source[index])
                if (
                    unicodedata.category(source[index]).startswith("M")
                    or 0x1F3FB <= cp <= 0x1F3FF
                    or 0xE0020 <= cp <= 0xE007F
                ):
                    index += 1
                elif source[index] == "\u200d":
                    index += 1
                    if index < len(source) and source[index] not in "\r\n":
                        index += 1
                else:
                    break
        yield SourceSpan(start, index), source[start:index]


def parse_plain_text(
    source: str, *, page: PageProfile | None = None, style: StyleProfile | None = None
) -> Document:
    # Reject lone surrogates rather than manufacturing Unicode scalar offsets.
    source.encode("utf-8")
    nodes = []
    pending = []
    node_id = new_id()
    start = 0
    for span, text in clusters(source):
        pending.append(Occurrence(new_id(), node_id, span, text))
        if text in ("\r", "\n", "\r\n"):
            nodes.append(Node(node_id, "Paragraph", SourceSpan(start, span.end), tuple(pending)))
            node_id, start, pending = new_id(), span.end, []
    # Keep an empty trailing paragraph: a final newline has visible vertical extent.
    nodes.append(Node(node_id, "Paragraph", SourceSpan(start, len(source)), tuple(pending)))
    return Document(
        new_id(), 0, source, tuple(nodes), page or PageProfile(), style or StyleProfile()
    )
