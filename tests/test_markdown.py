import json

import pytest

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown


def nodes(doc, kind):
    return [n for root in doc.nodes for n in root.walk() if n.kind == kind]


def test_exact_source_mapping_for_entities_escapes_code_and_repeated_labels():
    source = "# 标题\r\n\r\n[同文](https://example.com) 同文 &amp; &amp; \\* `&amp;`"
    doc = parse_markdown(source)
    pairs = [(o.text, source[o.span.start : o.span.end]) for o in doc.occurrences]
    assert pairs.count(("&", "&amp;")) == 2
    assert ("*", "\\*") in pairs
    assert ("&", "&") in pairs  # Code does not decode entities.
    repeated = [o for o in doc.occurrences if o.text == "同"]
    assert len({o.occurrence_id for o in repeated}) == 2
    assert repeated[0].span != repeated[1].span
    assert source[
        nodes(doc, "code_inline")[0].span.start : nodes(doc, "code_inline")[0].span.end
    ] == ("`&amp;`")
    assert dict(nodes(doc, "link")[0].attributes)["href"] == "https://example.com"


@pytest.mark.parametrize(
    "markup,kind", [("**A**", "strong"), ("***A***", "em"), ("~~A~~", "s"), ("_A_", "em")]
)
def test_formatting_node_spans_include_complete_markers(markup, kind):
    doc = parse_markdown(markup)
    node = nodes(doc, kind)[0]
    assert markup[node.span.start : node.span.end] == markup
    assert "".join(o.text for o in doc.occurrences) == "A"


def test_list_quote_hardbreak_softbreak_and_crlf_mapping():
    source = "> - 第一行  \r\n>   第二行\r\n>   第三行"
    doc = parse_markdown(source)
    assert nodes(doc, "blockquote") and nodes(doc, "bullet_list")
    assert len(nodes(doc, "hardbreak")) == len(nodes(doc, "softbreak")) == 1
    for o in doc.occurrences:
        if o.text != "\n":
            assert source[o.span.start : o.span.end] == o.text
        else:
            assert "\r\n" in source[o.span.start : o.span.end]


def test_pipe_table_maps_duplicate_cells_and_escaped_pipes():
    source = "| 1.0 | 1.0 |\n|:---|---:|\n| a\\|b | `c\\|d` |"
    doc = parse_markdown(source)
    assert len(nodes(doc, "th")) == len(nodes(doc, "td")) == 2
    ids = [n.node_id for r in doc.nodes for n in r.walk()]
    assert len(ids) == len(set(ids))
    ones = [o for o in doc.occurrences if o.text == "1"]
    assert len(ones) == 2 and ones[0].span != ones[1].span
    pipes = [o for o in doc.occurrences if o.text == "|"]
    assert len(pipes) == 2
    assert all(source[o.span.start : o.span.end] == "\\|" for o in pipes)


def test_code_html_and_image_remain_inert_and_preserve_raw_source():
    source = "```python\n$not_math$ &amp; **literal**\n```\n\n<table><tr><td>1</td></tr></table>\n\n![alt](missing.png)"
    doc = parse_markdown(source)
    assert not doc.diagnostics  # Parsing is inert; missing resources are diagnosed by layout.
    assert "".join(o.text for o in doc.occurrences) == "$not_math$ &amp; **literal**\n1\ufffcalt"
    assert nodes(doc, "fence")[0].raw_content == "$not_math$ &amp; **literal**\n"
    image = nodes(doc, "image")[0]
    assert source[image.span.start : image.span.end] == "![alt](missing.png)"
    table = nodes(doc, "table")[0]
    assert "<table>" in source[table.span.start : table.span.end]


def test_tab_indented_code_and_normalized_inline_code_have_ranges():
    doc = parse_markdown("\tcode\n\n`` a\r\nb ``")
    assert nodes(doc, "code_block")[0].raw_content == "code\n"
    assert "".join(o.text for o in doc.occurrences) == "code\na b"
    space = next(o for o in doc.occurrences if o.text == " ")
    assert doc.source[space.span.start : space.span.end] == "\r\n"


def test_parse_edit_undo_and_restore_preserve_untouched_occurrence_ids():
    session = SourceSession("正文 **1.20** &amp;\r\n第二行")
    before = parse_markdown(session)
    ids = [o.occurrence_id for o in before.occurrences]
    session.apply(0, 0, "新增段落\n\n")
    after = parse_markdown(session)
    assert [o.occurrence_id for o in after.occurrences][-len(ids) :] == ids
    restored = parse_markdown(SourceSession.restore(session.source, session.identity_record()))
    assert restored == after
    session.undo()
    reverted = parse_markdown(session)
    assert reverted.content_key == before.content_key
    assert reverted.revision > before.revision
    assert [o.occurrence_id for o in reverted.occurrences] == ids


def test_empty_input_and_excess_table_columns():
    assert parse_markdown("").nodes == ()
    with pytest.raises(ValueError, match="extra cells"):
        parse_markdown("a|b\n---|---\n1|2|3")
    with pytest.raises(ValueError, match="50 columns"):
        parse_markdown("|".join(["a"] * 51) + "\n" + "|".join(["---"] * 51))
    with pytest.raises(ValueError, match="nesting"):
        parse_markdown("> " * 40 + "deep")


def test_empty_and_autocompleted_cells_keep_distinct_node_ids():
    doc = parse_markdown("a|b|c\n---|---|---\n|||\n1\n")
    ids = [n.node_id for r in doc.nodes for n in r.walk()]
    assert len(ids) == len(set(ids))
    assert len(nodes(doc, "td")) == 6


def test_structure_cli_preserves_source_and_reports_capability(tmp_path, capsys):
    import json

    from inkstruct.cli import main

    path = tmp_path / "source.md"
    path.write_bytes("# 标题\r\n\r\n**1.20**".encode())
    assert main(["document", "inspect", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["document"]["source"].encode() == path.read_bytes()
    assert not result["machine_export_ready"] and not result["layout_ready"]


def test_math_does_not_produce_misleading_prose_capture_tasks(tmp_path, capsys):
    from inkstruct.cli import main

    assert not parse_markdown("$x$ \\$ `x$`").diagnostics
    assert not parse_markdown("\\$ `x$`").diagnostics
    source = tmp_path / "math.md"
    source.write_text("$\\alpha + 1$")
    output = tmp_path / "tasks.csv"
    assert main(["document", "resources", str(source), "--capture-csv", str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {g["character"] for g in report["gaps"]} == {"α", "+", "1"}
    assert "alpha" not in output.read_text(encoding="utf-8-sig")
    assert not report["machine_export_ready"]
