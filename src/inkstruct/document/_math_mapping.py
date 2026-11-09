"""Dollar delimiters at parser boundaries, preserving LocatedString ranges."""

from .schema import SourceSpan


def inline_math_end(source, start, *, limit=None):
    """Return end-exclusive/body bounds/error; never cross a source line."""
    limit = len(source) if limit is None else limit
    if source[start : min(start + 2, limit)] == "$$":
        return start + 2, start + 2, start + 2, "Display delimiters must be on separate lines"
    at = start + 1
    while at < limit and source[at] != "\n":
        if source[at] == "\\":
            at += 2
            continue
        if source[at] == "$":
            return at + 1, start + 1, at, None
        at += 1
    return (
        start + 1,
        start + 1,
        start + 1,
        "Unclosed inline math delimiter; escape a literal dollar",
    )


def inline_math(state, silent):
    start = state.pos
    if state.src[start : start + 1] != "$":
        return False
    end, a, b, error = inline_math_end(state.src, start, limit=state.posMax)
    if not silent:
        token = state.push("math_inline", "math", 0)
        token.content = state.src[a:b]
        token.markup = "$"
        token.meta["source_span"] = SourceSpan(
            state.src.ranges[start].start, state.src.ranges[end - 1].end
        )
        token.meta["math_error"] = error
    state.pos = end
    return True


def block_math(state, start, end, silent):
    if state.is_code_block(start):
        return False
    a = state.bMarks[start] + state.tShift[start]
    if state.src[a : state.eMarks[start]].strip() != "$$":
        return False
    if silent:
        return True
    closing = start + 1
    found = False
    while closing < end:
        pos = state.bMarks[closing] + state.tShift[closing]
        if pos < state.eMarks[closing] and state.sCount[closing] < state.blkIndent:
            break
        if (
            not state.is_code_block(closing)
            and state.src[pos : state.eMarks[closing]].strip() == "$$"
        ):
            found = True
            break
        closing += 1
    state.line = closing + int(found)
    token = state.push("math_block", "math", 0)
    token.block = True
    token.map = [start, state.line]
    token.content = state.getLines(start + 1, closing, state.blkIndent, False)
    token.markup = "$$"
    last = state.eMarks[closing if found else max(start, closing - 1)]
    token.meta["source_span"] = SourceSpan(
        state.src.ranges[a].start, state.src.ranges[last - 1].end
    )
    token.meta["math_error"] = None if found else "Unclosed display math delimiter"
    return True
