from file.header_footer import filter_repeated_headers_footers
from file.models import BlockType, ContentBlock


def test_repeated_headers_and_page_numbers_are_filtered() -> None:
    blocks = []
    order = 0
    for page in range(1, 5):
        for text in ("Medical Journal 2026", f"第 {page} 页正文", str(page)):
            blocks.append(
                ContentBlock(
                    id=f"b{order}",
                    page=page,
                    order=order,
                    type=BlockType.TEXT,
                    text=text,
                )
            )
            order += 1

    kept, removed = filter_repeated_headers_footers(blocks, edge_blocks=1)

    assert [block.text for block in kept] == [f"第 {page} 页正文" for page in range(1, 5)]
    assert len(removed) == 8
