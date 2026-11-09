"""Opt-in static Obsidian syntax. No vault discovery, URL execution or transclusion."""

import re

from markdown_it.token import Token

from .schema import SourceSpan

OBSIDIAN_VERSION = "inkstruct-obsidian-static-v1/markdown-it-py-4.0.0/break-commands-v2"


def wiki_link(state, silent):
    start = state.pos
    embedded = state.src.startswith("![[", start)
    prefix = 3 if embedded else 2
    if not embedded and not state.src.startswith("[[", start):
        return False
    end = state.src.find("]]", start + prefix, min(state.posMax, start + 4096))
    if end < 0:
        return False
    inner = state.src[start + prefix : end]
    if "\n" in inner or "[" in inner or "]" in inner:
        return False
    parts = inner.split("|", 1)
    target = parts[0].strip()
    split = inner.find("|")
    visible = inner[split + 1 :].strip() if split >= 0 else inner.strip()
    error = ""
    if not target or not visible or "|" in visible or any(ord(c) < 32 for c in inner):
        error = "A wiki reference needs a target and one non-empty display label"
    elif embedded and split < 0:
        error = "Static embeds require an explicit display label: ![[target|label]]"
    elif (
        embedded
        and re.search(r"\.(?:png|jpe?g|gif|webp|bmp|svg|pdf)(?:#|$)", target, re.IGNORECASE)
        and re.fullmatch(r"\d+(?:x\d+)?", str(visible))
    ):
        error = "Image embed sizing is unsupported here; use a Markdown image with image settings"
    if not silent:
        token = state.push("wiki_embed" if embedded else "wiki_link", "", 0)
        token.content = visible
        token.attrs = {"target": str(target), "explicit_label": str(split >= 0).lower()}
        token.meta["source_span"] = SourceSpan(
            state.src.ranges[start].start, state.src.ranges[end + 1].end
        )
        if error:
            token.meta["obsidian_error"] = error
    state.pos = end + 2
    return True


def callout_core(state):
    """Convert only the first direct paragraph of a parsed blockquote, before inline parsing."""
    tokens = state.tokens
    stack, recognized = [], {}
    for i, token in enumerate(tokens):
        if token.type == "blockquote_open":
            stack.append(i)
        elif token.type == "blockquote_close":
            start = stack.pop()
            if (
                start + 3 >= i
                or tokens[start + 1].type != "paragraph_open"
                or tokens[start + 2].type != "inline"
                or tokens[start + 3].type != "paragraph_close"
            ):
                continue
            inline = tokens[start + 2]
            first = inline.content.split("\n", 1)[0]
            match = re.fullmatch(
                r"\[!([A-Za-z][A-Za-z0-9_-]{0,63})\]([+-]?)(?:[ \t]+(.*))?", str(first)
            )
            if not match:
                continue
            recognized[start] = (i, match, len(first))
    replacements = {}
    for start, (end, match, first_len) in recognized.items():
        opened, closed = tokens[start], tokens[end]
        opened.type, closed.type = "callout_open", "callout_close"
        opened.attrSet("callout_type", match[1].lower())
        opened.attrSet("fold", {"+": "expanded", "-": "collapsed", "": "none"}[match[2]])
        inline = tokens[start + 2]
        content = inline.content
        title = content[match.start(3) : first_len].strip() if match[3] else content[0:0]
        if not title:
            # A generated title still maps to the original identifier characters.
            from ._markdown_mapping import LocatedString

            raw = content[match.start(1) : match.end(1)]
            title = LocatedString(str(raw).capitalize(), raw.ranges)
        title_span = SourceSpan(content.ranges[0].start, content.ranges[first_len - 1].end)
        title_open = Token("callout_title_open", "p", 1)
        title_open.meta["source_span"] = title_span
        title_inline = Token("inline", "", 0)
        title_inline.content = title
        title_inline.meta["source_span"] = title_span
        title_close = Token("callout_title_close", "p", -1)
        title_close.meta["source_span"] = title_span
        replacement = [title_open, title_inline, title_close]
        body = content[first_len + 1 :]
        if body:
            inline.content = body
            inline.meta["source_span"] = SourceSpan(body.ranges[0].start, body.ranges[-1].end)
            tokens[start + 1].meta["source_span"] = inline.meta["source_span"]
            tokens[start + 3].meta["source_span"] = inline.meta["source_span"]
            replacement.extend([tokens[start + 1], inline, tokens[start + 3]])
        replacements[start + 1] = replacement
    result, i = [], 0
    while i < len(tokens):
        if i in replacements:
            result.extend(replacements[i])
            i += 3
        else:
            result.append(tokens[i])
            i += 1
    state.tokens[:] = result
