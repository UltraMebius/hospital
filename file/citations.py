"""Reference-section extraction from normalized content blocks."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .models import BlockType, Citation, ContentBlock

_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*(参考文献|参考资料|references?|bibliography)\s*[:：]?\s*$",
    flags=re.IGNORECASE,
)
_ENTRY_RE = re.compile(r"(?m)(?=^\s*(?:\[?\d+\]?)[.、\]]\s*)")


def extract_citations(blocks: Sequence[ContentBlock]) -> list[Citation]:
    start: int | None = None
    for index, block in enumerate(blocks):
        if block.type in {BlockType.TEXT, BlockType.TITLE} and _HEADING_RE.match(block.text):
            start = index + 1
            break
    if start is None:
        return []

    citations: list[Citation] = []
    citation_index = 0
    for block in blocks[start:]:
        if block.type not in {BlockType.TEXT, BlockType.TITLE}:
            continue
        text = block.text.strip()
        if not text:
            continue
        entries = [item.strip() for item in _ENTRY_RE.split(text) if item.strip()]
        for entry in entries:
            citations.append(
                Citation(
                    id=f"citation-{citation_index:04d}",
                    page=block.page,
                    order=citation_index,
                    raw_text=entry,
                    metadata={"source_block_id": block.id},
                )
            )
            citation_index += 1
    return citations
