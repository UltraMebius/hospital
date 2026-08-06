"""Conservative repeated-margin detection for page-oriented parser output."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Sequence

from .models import BlockType, ContentBlock

_SPACE_RE = re.compile(r"\s+")
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d+(?:\s*/\s*\d+)?$|^第?\s*\d+\s*页$", re.I)


def _signature(text: str) -> str:
    normalized = _SPACE_RE.sub(" ", text).strip().casefold()
    if len(normalized) > 160:
        return ""
    if _PAGE_NUMBER_RE.match(normalized):
        return "<page-number>"
    return normalized


def filter_repeated_headers_footers(
    blocks: Sequence[ContentBlock],
    *,
    edge_blocks: int = 2,
    repeat_ratio: float = 0.5,
    minimum_pages: int = 3,
) -> tuple[list[ContentBlock], list[ContentBlock]]:
    """Remove short text repeated near the top or bottom of enough pages.

    MinerU's content-list export contains a page index but often no bounding box.
    The filter therefore only considers the first and last ``edge_blocks`` text
    blocks on each page. Top and bottom signatures are counted independently.
    """

    if edge_blocks < 1:
        raise ValueError("edge_blocks must be at least 1")
    if not 0 < repeat_ratio <= 1:
        raise ValueError("repeat_ratio must be in (0, 1]")

    by_page: dict[int, list[ContentBlock]] = defaultdict(list)
    for block in blocks:
        by_page[block.page].append(block)
    if len(by_page) < minimum_pages:
        return list(blocks), []

    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    positions: dict[int, set[tuple[str, int]]] = defaultdict(set)
    for page, page_blocks in by_page.items():
        candidates = [
            block
            for block in sorted(page_blocks, key=lambda item: item.order)
            if block.type in {BlockType.TEXT, BlockType.TITLE}
            and block.text.strip()
            and block.metadata.get("reading_role", "body") == "body"
            and block.metadata.get("document_role", "body") not in {"first_page_header", "footnote"}
        ]
        for position, items in (
            ("header", candidates[:edge_blocks]),
            ("footer", candidates[-edge_blocks:]),
        ):
            for block in items:
                signature = _signature(block.text)
                if signature:
                    occurrences[(position, signature)].add(page)
                    positions[block.order].add((position, page))

    required = max(minimum_pages, math.ceil(len(by_page) * repeat_ratio))
    repeated = {key for key, pages in occurrences.items() if len(pages) >= required}

    kept: list[ContentBlock] = []
    removed: list[ContentBlock] = []
    for block in blocks:
        signature = _signature(block.text)
        matches = any(
            (position, signature) in repeated
            for position, page in positions.get(block.order, set())
            if page == block.page
        )
        (removed if matches else kept).append(block)
    return kept, removed
