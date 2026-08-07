from file.table_markdown import extracted_table_to_markdown, html_table_to_markdown


def test_html_table_to_markdown_preserves_spans_entities_and_pipes() -> None:
    source = """
    <table>
      <tr><th rowspan="2">项目</th><th colspan="2">结果</th></tr>
      <tr><td>&amp;lt;5</td><td>A|B</td></tr>
    </table>
    """

    assert html_table_to_markdown(source) == (
        "| 项目 | 结果 |  |\n| --- | --- | --- |\n| 项目 | <5 | A\\|B |\n"
    )


def test_extracted_table_to_markdown_merges_split_headers_and_wrapped_rows() -> None:
    rows = [
        ["建", "建议", "证据"],
        ["议", "等级", "水平"],
        [None, None, None],
        ["建议定期监测", "Ⅰ", "B"],
        ["并确认房颤", None, None],
    ]

    assert extracted_table_to_markdown(rows) == (
        "| 建议 | 建议等级 | 证据水平 |\n| --- | --- | --- |\n| 建议定期监测并确认房颤 | Ⅰ | B |\n"
    )


def test_table_markdown_restores_html_and_detached_formula_subscripts() -> None:
    assert (
        html_table_to_markdown(
            "<table><tr><td>名称</td></tr><tr><td>H<sub>2</sub>O</td></tr></table>"
        )
        == "| 名称 |\n| --- |\n| H₂O |\n"
    )

    rows = [
        ["建议", "等级"],
        ["使用CHA DS -VASc评分\n2 2", "I"],
    ]
    assert "CHA₂DS₂-VASc评分" in extracted_table_to_markdown(rows)
