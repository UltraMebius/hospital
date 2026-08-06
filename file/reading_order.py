"""Document-level column detection and page-level geometric reading order."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .pdf_backend import NativeTextBlock

_KEYWORDS_RE = re.compile(r"(?:关键词|关键字|key\s*words?)\s*[:：】]", re.I)
_ABSTRACT_RE = re.compile(r"(?:摘要|abstract)\s*[:：】]", re.I)


@dataclass(frozen=True)
class LayoutDecision:
    body_columns: int
    body_start_page: int
    body_start_y: float
    evidence_pages: tuple[int, ...]
    page_evidence: dict[int, dict[str, int]]

    def to_dict(self) -> dict[str, object]:
        return {
            "body_columns": self.body_columns,
            "body_start_page": self.body_start_page,
            "body_start_y": self.body_start_y,
            "evidence_pages": list(self.evidence_pages),
            "page_evidence": {str(page): evidence for page, evidence in self.page_evidence.items()},
        }


def _visible_characters(text: str) -> int:
    return sum(not character.isspace() for character in text)


def _body_start(
    blocks_by_page: Mapping[int, Sequence[NativeTextBlock]],
) -> tuple[int, float]:
    keyword_markers: list[tuple[int, float]] = []
    abstract_markers: list[tuple[int, float]] = []
    for page in sorted(blocks_by_page)[:2]:
        for block in blocks_by_page[page]:
            if block.bbox is None:
                continue
            marker = (page, block.bbox[3])
            if _KEYWORDS_RE.search(block.text):
                keyword_markers.append(marker)
            elif _ABSTRACT_RE.search(block.text):
                abstract_markers.append(marker)
    if keyword_markers:
        return max(keyword_markers)
    if abstract_markers:
        return max(abstract_markers)
    first_page = min(blocks_by_page, default=1)
    return first_page, 0.0


def _is_after_body_start(block: NativeTextBlock, start_page: int, start_y: float) -> bool:
    if block.page > start_page:
        return True
    if block.page < start_page or block.bbox is None:
        return False
    return block.bbox[1] >= start_y


def detect_body_columns(
    blocks_by_page: Mapping[int, Sequence[NativeTextBlock]],
    page_sizes: Mapping[int, tuple[float, float]],
    *,
    minimum_characters_per_column: int = 80,
) -> LayoutDecision:
    """Detect whether the article body predominantly uses one or two columns."""

    start_page, start_y = _body_start(blocks_by_page)
    page_evidence: dict[int, dict[str, int]] = {}
    eligible_pages: list[int] = []
    evidence_pages: list[int] = []

    for page in sorted(blocks_by_page):
        page_width = page_sizes.get(page, (0.0, 0.0))[0]
        if page_width <= 0:
            continue
        midpoint = page_width / 2
        left_characters = 0
        right_characters = 0
        body_characters = 0
        for block in blocks_by_page[page]:
            if block.bbox is None or not _is_after_body_start(block, start_page, start_y):
                continue
            if _ABSTRACT_RE.search(block.text) or _KEYWORDS_RE.search(block.text):
                continue
            x0, _, x1, _ = block.bbox
            width = x1 - x0
            characters = _visible_characters(block.text)
            body_characters += characters
            if width > page_width * 0.62:
                continue
            center = (x0 + x1) / 2
            if center < midpoint - page_width * 0.04:
                left_characters += characters
            elif center > midpoint + page_width * 0.04:
                right_characters += characters

        if body_characters >= minimum_characters_per_column:
            eligible_pages.append(page)
        page_evidence[page] = {
            "body_characters": body_characters,
            "left_characters": left_characters,
            "right_characters": right_characters,
        }
        if (
            left_characters >= minimum_characters_per_column
            and right_characters >= minimum_characters_per_column
        ):
            evidence_pages.append(page)

    required_pages = 1 if len(eligible_pages) <= 2 else max(2, math.ceil(len(eligible_pages) * 0.3))
    columns = 2 if len(evidence_pages) >= required_pages else 1
    return LayoutDecision(
        body_columns=columns,
        body_start_page=start_page,
        body_start_y=start_y,
        evidence_pages=tuple(evidence_pages),
        page_evidence=page_evidence,
    )


def _natural_key(block: NativeTextBlock) -> tuple[float, float]:
    if block.bbox is None:
        return (float("inf"), float("inf"))
    return (block.bbox[1], block.bbox[0])


def _column_key(block: NativeTextBlock, page_width: float) -> tuple[int, float, float]:
    if block.bbox is None:
        return (2, float("inf"), float("inf"))
    x0, y0, x1, _ = block.bbox
    column = 0 if (x0 + x1) / 2 < page_width / 2 else 1
    return (column, y0, x0)


def order_page_blocks(
    blocks: Sequence[NativeTextBlock],
    page_width: float,
    *,
    columns: int,
) -> list[NativeTextBlock]:
    """Order one page and append notes/references after its main reading flow."""

    main_blocks = [block for block in blocks if block.reading_role == "body"]
    page_end_blocks = [block for block in blocks if block.reading_role != "body"]
    ordered_main = _order_geometric(main_blocks, page_width, columns)
    return _merge_line_wrapped_terms(ordered_main, page_width) + _order_geometric(
        page_end_blocks, page_width, columns
    )


def _merge_line_wrapped_terms(
    blocks: Sequence[NativeTextBlock], page_width: float
) -> list[NativeTextBlock]:
    """Join an ASCII/scientific term split immediately after a hyphen."""

    merged: list[NativeTextBlock] = []
    for block in blocks:
        if not merged:
            merged.append(block)
            continue
        previous = merged[-1]
        if previous.bbox is None or block.bbox is None:
            merged.append(block)
            continue
        previous_height = previous.bbox[3] - previous.bbox[1]
        vertical_gap = block.bbox[1] - previous.bbox[3]
        same_column = abs(block.bbox[0] - previous.bbox[0]) <= max(8.0, page_width * 0.04)
        wrapped_term = bool(
            re.search(r"[A-Za-z0-9₀-₉]+-$", previous.text.rstrip())
            and re.match(r"^[A-Za-z]", block.text.lstrip())
        )
        if (
            previous.page == block.page
            and same_column
            and -2.0 <= vertical_gap <= max(5.0, previous_height * 0.8)
            and wrapped_term
        ):
            merged[-1] = NativeTextBlock(
                page=previous.page,
                text=f"{previous.text.rstrip()}{block.text.lstrip()}",
                bbox=(
                    min(previous.bbox[0], block.bbox[0]),
                    min(previous.bbox[1], block.bbox[1]),
                    max(previous.bbox[2], block.bbox[2]),
                    max(previous.bbox[3], block.bbox[3]),
                ),
                reading_role=previous.reading_role,
            )
        else:
            merged.append(block)
    return merged


def _order_geometric(
    blocks: Sequence[NativeTextBlock], page_width: float, columns: int
) -> list[NativeTextBlock]:
    """Apply the natural or column-aware order to one group of page blocks."""

    if columns == 1 or page_width <= 0:
        return sorted(blocks, key=_natural_key)

    spanning: list[NativeTextBlock] = []
    column_blocks: list[NativeTextBlock] = []
    midpoint = page_width / 2
    gutter = page_width * 0.04
    for block in blocks:
        if block.bbox is None:
            spanning.append(block)
            continue
        x0, _, x1, _ = block.bbox
        width = x1 - x0
        crosses_gutter = x0 < midpoint - gutter and x1 > midpoint + gutter
        if width >= page_width * 0.68 or crosses_gutter:
            spanning.append(block)
        else:
            column_blocks.append(block)

    if not spanning:
        return sorted(column_blocks, key=lambda block: _column_key(block, page_width))

    ordered: list[NativeTextBlock] = []
    remaining = set(range(len(column_blocks)))
    for span in sorted(spanning, key=_natural_key):
        span_y = span.bbox[1] if span.bbox is not None else float("inf")
        band_indices = [
            index
            for index in remaining
            if column_blocks[index].bbox is not None
            and (column_blocks[index].bbox[1] + column_blocks[index].bbox[3]) / 2 < span_y
        ]
        ordered.extend(
            sorted(
                (column_blocks[index] for index in band_indices),
                key=lambda block: _column_key(block, page_width),
            )
        )
        remaining.difference_update(band_indices)
        ordered.append(span)
    ordered.extend(
        sorted(
            (column_blocks[index] for index in remaining),
            key=lambda block: _column_key(block, page_width),
        )
    )
    return ordered
