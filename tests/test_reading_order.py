from file.pdf_backend import (
    NativeTextBlock,
    _is_formula_or_bibliography_number,
    _split_line,
)
from file.reading_order import detect_body_columns, order_page_blocks


def _block(
    page: int,
    text: str,
    bbox: tuple[float, float, float, float],
    reading_role: str = "body",
) -> NativeTextBlock:
    return NativeTextBlock(
        page=page,
        text=text,
        bbox=bbox,
        reading_role=reading_role,
    )


def test_detects_two_column_body_after_abstract_and_keywords() -> None:
    blocks = {
        1: [
            _block(1, "文章标题", (40, 20, 560, 60)),
            _block(1, "【摘要】这部分不参与栏数判断", (60, 80, 540, 160)),
            _block(1, "【关键词】医学；指南", (60, 170, 540, 200)),
            _block(1, "左栏正文内容" * 20, (40, 230, 280, 500)),
            _block(1, "右栏正文内容" * 20, (320, 230, 560, 500)),
        ],
        2: [
            _block(2, "第二页左栏" * 20, (40, 40, 280, 700)),
            _block(2, "第二页右栏" * 20, (320, 40, 560, 700)),
        ],
    }

    decision = detect_body_columns(blocks, {1: (600, 800), 2: (600, 800)})

    assert decision.body_columns == 2
    assert decision.body_start_page == 1
    assert decision.body_start_y == 200
    assert decision.evidence_pages == (1, 2)


def test_two_column_order_reads_left_column_before_right_column() -> None:
    blocks = [
        _block(1, "页眉", (40, 10, 560, 30)),
        _block(1, "右栏第一段", (320, 100, 560, 150)),
        _block(1, "左栏第一段", (40, 100, 280, 150)),
        _block(1, "右栏第二段", (320, 200, 560, 250)),
        _block(1, "左栏第二段", (40, 200, 280, 250)),
        _block(1, "页脚", (40, 760, 560, 780)),
    ]

    ordered = order_page_blocks(blocks, 600, columns=2)

    assert [block.text for block in ordered] == [
        "页眉",
        "左栏第一段",
        "左栏第二段",
        "右栏第一段",
        "右栏第二段",
        "页脚",
    ]


def test_page_references_and_notes_are_appended_after_two_column_body() -> None:
    blocks = [
        _block(1, "left body", (40, 100, 280, 150)),
        _block(
            1,
            "left reference [1]",
            (200, 145, 250, 155),
            "page_end_reference",
        ),
        _block(1, "right body", (320, 100, 560, 150)),
        _block(
            1,
            "right reference [2]",
            (500, 145, 550, 155),
            "page_end_reference",
        ),
        _block(1, "page note", (40, 730, 560, 750), "page_end_note"),
    ]

    ordered = order_page_blocks(blocks, 600, columns=2)

    assert [block.text for block in ordered] == [
        "left body",
        "right body",
        "left reference [1]",
        "right reference [2]",
        "page note",
    ]


def test_inline_superscript_reference_is_split_from_sentence() -> None:
    spans = [
        {"text": "body", "size": 10.0, "flags": 0, "bbox": (10, 10, 30, 20)},
        {"text": "[", "size": 5.8, "flags": 0, "bbox": (30, 8, 35, 14)},
        {"text": "1", "size": 5.8, "flags": 0, "bbox": (34, 8, 38, 14)},
        {"text": "]", "size": 5.8, "flags": 0, "bbox": (37, 8, 42, 14)},
        {"text": ". more", "size": 10.0, "flags": 0, "bbox": (42, 10, 72, 20)},
    ]

    fragments = _split_line(spans, body_font_size=10.0)

    assert [(text, role) for text, _, role in fragments] == [
        ("body", "body"),
        ("[1]", "page_end_reference"),
        (". more", "body"),
    ]


def test_formula_subscripts_are_merged_into_the_medical_term() -> None:
    spans = [
        {
            "text": "CHA",
            "size": 10.0,
            "flags": 0,
            "origin": (10, 20),
            "bbox": (10, 10, 30, 22),
        },
        {
            "text": "2",
            "size": 5.8,
            "flags": 0,
            "origin": (30, 22.4),
            "bbox": (30, 16, 34, 23),
        },
        {
            "text": " DS",
            "size": 10.0,
            "flags": 0,
            "origin": (34, 22.4),
            "bbox": (34, 10, 46, 22),
        },
        {
            "text": "2",
            "size": 5.8,
            "flags": 0,
            "origin": (46, 22.4),
            "bbox": (46, 16, 50, 23),
        },
        {
            "text": " -VASc score",
            "size": 10.0,
            "flags": 0,
            "origin": (50, 22.4),
            "bbox": (50, 10, 100, 22),
        },
    ]

    fragments = _split_line(spans, body_font_size=10.0)

    assert [(text, role) for text, _, role in fragments] == [("CHA₂DS₂-VASc score", "body")]


def test_formula_exponents_and_bibliography_issue_numbers_are_not_references() -> None:
    assert _is_formula_or_bibliography_number("2", "BMI < 40 kg/m", "、无病史")
    assert _is_formula_or_bibliography_number("3", "β", "受体激动剂")
    assert _is_formula_or_bibliography_number("(5)", "2012,6", ": 354-363")
    assert not _is_formula_or_bibliography_number("[5]", "正文", "。后文")


def test_single_column_order_remains_top_to_bottom() -> None:
    blocks = [
        _block(1, "第二段", (40, 200, 560, 250)),
        _block(1, "第一段", (40, 100, 560, 150)),
    ]

    ordered = order_page_blocks(blocks, 600, columns=1)

    assert [block.text for block in ordered] == ["第一段", "第二段"]


def test_medical_term_split_after_hyphen_is_kept_in_one_block() -> None:
    blocks = [
        _block(1, "根据CHA₂DS₂-", (40, 100, 260, 112)),
        _block(1, "VASc评分进行判断", (40, 115, 260, 127)),
    ]

    ordered = order_page_blocks(blocks, 600, columns=1)

    assert [block.text for block in ordered] == ["根据CHA₂DS₂-VASc评分进行判断"]
