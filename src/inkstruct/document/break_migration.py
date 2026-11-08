"""Migrate the isolated v1 paging aliases without writing the original package."""

from .break_commands import PAGE_COMMANDS, scan_break
from .editing import SourceSession
from .markdown import parse_markdown


def migrate_v1_breaks(session, flow):
    document = parse_markdown(
        session, dialect=flow.markdown_dialect, field_blocks=flow.named_fields
    )
    spans = set()
    for root in document.nodes:
        for node in root.walk():
            if node.kind != "pagebreak" or dict(node.attributes).get("strength", "4") != "4":
                continue
            match = scan_break(session.source, node.span.start)
            if match and not match.error and match.name in PAGE_COMMANDS:
                spans.add((node.span.start, match.end))
    for start, end in sorted(spans, reverse=True):
        # An explicit terminator also protects text after an old [4] option.
        # Keep the leading slash anchor: a paragraph/list item may start here,
        # and its generated marker choices derive from that unchanged anchor.
        session.apply(start + 1, end, "framebreak{}")
    if not spans:
        return session, ""
    # Migration is a load transaction, not an undoable content edit. All other
    # scalar identities, embedded resources, reviews and frozen choices survive.
    session = SourceSession.restore(session.source, session.identity_record())
    notice = (
        f"已将旧项目的 {len(spans)} 处换框命令迁移为 \\framebreak；"
        "原项目文件未改写，请另存迁移后的项目。"
    )
    return session, notice
