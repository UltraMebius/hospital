from file.document_order import classify_document_blocks, order_document_blocks
from file.models import BlockType, ContentBlock


def _block(
    block_id: str,
    page: int,
    order: int,
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    reading_role: str = "body",
) -> ContentBlock:
    return ContentBlock(
        id=block_id,
        page=page,
        order=order,
        type=BlockType.TEXT,
        text=text,
        bbox=bbox,
        metadata={"reading_role": reading_role},
    )


def test_document_sections_follow_required_semantic_order() -> None:
    blocks = [
        _block("header", 1, 0, "Journal 2026 Vol. 1", (30, 20, 560, 30)),
        _block("expert", 1, 1, "Expert biography unrelated to title", (50, 40, 550, 120)),
        _block("title", 1, 2, "Clinical article title", (50, 130, 550, 165)),
        _block("authors", 1, 3, "Author One, Author Two", (100, 175, 500, 189)),
        _block("abstract", 1, 4, "Abstract: summary text", (50, 210, 550, 225)),
        _block("keywords", 1, 5, "Keywords: medicine; evidence", (50, 230, 550, 245)),
        _block("body-1", 1, 6, "Body page one", (50, 270, 280, 290)),
        _block("inline-ref", 1, 7, "[1]", (250, 285, 260, 292), reading_role="page_end_reference"),
        _block("body-2", 2, 8, "Body page two", (50, 50, 280, 70)),
        _block("note", 2, 9, "Note: page note", (50, 730, 550, 745), reading_role="page_end_note"),
        _block("references-heading", 2, 10, "References", (50, 500, 200, 520)),
        _block("reference-entry", 2, 11, "[1] Author. Paper.", (50, 530, 500, 550)),
    ]

    classified = classify_document_blocks(blocks, article_name="Clinical article title")
    ordered = order_document_blocks(classified)

    assert [block.id for block in ordered] == [
        "title",
        "authors",
        "abstract",
        "keywords",
        "body-1",
        "body-2",
        "header",
        "expert",
        "note",
        "inline-ref",
        "references-heading",
        "reference-entry",
    ]
    assert [block.metadata["document_role"] for block in ordered] == [
        "title",
        "title",
        "abstract",
        "keywords",
        "body",
        "body",
        "first_page_header",
        "first_page_header",
        "footnote",
        "references",
        "references",
        "references",
    ]
