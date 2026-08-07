"""Document-level semantic ordering for normalized content blocks."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from difflib import SequenceMatcher

from .models import BlockType, ContentBlock

_ABSTRACT_RE = re.compile(r"^\s*(?:[【\[［]\s*)?(?:摘要|abstract)(?:\s*[】\]］])?\s*[:：]?", re.I)
_KEYWORDS_RE = re.compile(
    r"^\s*(?:[【\[［]\s*)?(?:关键词|关键字|key\s*words?)(?:\s*[】\]］])?\s*[:：]?",
    re.I,
)
_REFERENCES_RE = re.compile(
    r"^\s*#{0,6}\s*(?:参考文献|参考资料|references?|bibliography)\s*[:：]?\s*$",
    re.I,
)

_ROLE_PRIORITY = {
    "title": 0,
    "abstract": 1,
    "keywords": 2,
    "body": 3,
    "first_page_header": 4,
    "footnote": 5,
    "references": 6,
}


def _is_text(block: ContentBlock) -> bool:
    return block.type in {BlockType.TEXT, BlockType.TITLE} and bool(block.text.strip())


def _height(block: ContentBlock) -> float:
    if block.bbox is None:
        return 0.0
    return max(0.0, block.bbox[3] - block.bbox[1])


def _normalized_title(text: str) -> str:
    return "".join(character.casefold() for character in text if character.isalnum())


def _title_start_from_name(
    blocks: Sequence[ContentBlock], indices: Sequence[int], article_name: str
) -> int | None:
    target = _normalized_title(article_name)
    if not target:
        return None
    best: tuple[float, int] | None = None
    for offset, start in enumerate(indices):
        for length in range(1, 4):
            window = indices[offset : offset + length]
            if len(window) != length or any(
                right != left + 1 for left, right in zip(window, window[1:], strict=False)
            ):
                continue
            candidate = _normalized_title("".join(blocks[index].text for index in window))
            if not candidate:
                continue
            score = SequenceMatcher(None, target, candidate).ratio()
            if best is None or score > best[0]:
                best = score, start
    return best[1] if best is not None and best[0] >= 0.35 else None


def _keyword_segment_end(
    blocks: Sequence[ContentBlock], page_one: Sequence[int], marker: int
) -> int:
    position = page_one.index(marker)
    if position + 1 >= len(page_one):
        return marker
    next_index = page_one[position + 1]
    current = blocks[marker]
    following = blocks[next_index]
    if _ABSTRACT_RE.match(following.text) or _KEYWORDS_RE.match(following.text):
        return marker
    if current.bbox is None or following.bbox is None:
        return marker
    return next_index if following.bbox[1] - current.bbox[3] <= 6.0 else marker


def classify_document_blocks(
    blocks: Sequence[ContentBlock], *, article_name: str = ""
) -> list[ContentBlock]:
    """Assign semantic roles used by the final document-level ordering."""

    result = list(blocks)
    roles = ["body"] * len(result)
    for index, block in enumerate(result):
        reading_role = block.metadata.get("reading_role")
        if reading_role == "page_end_note":
            roles[index] = "footnote"
        elif reading_role == "page_end_reference":
            roles[index] = "references"

    reference_heading = next(
        (
            index
            for index, block in enumerate(result)
            if _is_text(block) and _REFERENCES_RE.fullmatch(block.text)
        ),
        None,
    )
    if reference_heading is not None:
        for index in range(reference_heading, len(result)):
            roles[index] = "references"

    page_one = [
        index
        for index, block in enumerate(result)
        if block.page == 1 and _is_text(block) and roles[index] == "body"
    ]
    abstract_indices = [index for index in page_one if _ABSTRACT_RE.match(result[index].text)]
    keywords_indices = [index for index in page_one if _KEYWORDS_RE.match(result[index].text)]
    front_markers = sorted([*abstract_indices, *keywords_indices])
    front_limit = front_markers[0] if front_markers else None
    title_pool = [index for index in page_one if front_limit is None or index < front_limit]
    title_start = _title_start_from_name(result, title_pool, article_name)
    if title_start is None and title_pool:
        tallest = max((_height(result[index]) for index in title_pool), default=0.0)
        if tallest > 0:
            candidates = [
                index
                for index in title_pool
                if _height(result[index]) >= tallest * 0.75
                and len(re.sub(r"\s+", "", result[index].text)) >= 4
            ]
        else:
            candidates = [index for index in title_pool if result[index].type is BlockType.TITLE]
        if candidates:
            title_start = min(candidates)

    keyword_ends = [_keyword_segment_end(result, page_one, marker) for marker in keywords_indices]
    front_end = max(keyword_ends, default=front_limit or (title_start or 0)) + 1

    if title_start is not None:
        title_end = front_end if front_markers else title_start + 1
        for index in page_one:
            if index < title_start:
                roles[index] = "first_page_header"
            elif title_start <= index < title_end:
                roles[index] = "title"

    for abstract_index in abstract_indices:
        abstract_end = next(
            (index for index in keywords_indices if index > abstract_index),
            abstract_index + 1,
        )
        for index in page_one:
            if abstract_index <= index < abstract_end:
                roles[index] = "abstract"
    for keywords_index, keywords_end in zip(keywords_indices, keyword_ends, strict=True):
        for index in page_one:
            if keywords_index <= index <= keywords_end:
                roles[index] = "keywords"

    for index, block in enumerate(result):
        forced_role = block.metadata.get("forced_document_role")
        if forced_role in _ROLE_PRIORITY:
            roles[index] = str(forced_role)

    return [
        replace(block, metadata={**block.metadata, "document_role": roles[index]})
        for index, block in enumerate(result)
    ]


def order_document_blocks(blocks: Sequence[ContentBlock]) -> list[ContentBlock]:
    """Order semantic sections while preserving order inside each section."""

    indexed = list(enumerate(blocks))
    indexed.sort(
        key=lambda item: (
            _ROLE_PRIORITY.get(item[1].metadata.get("document_role", "body"), 3),
            item[0],
        )
    )
    return [replace(block, order=index) for index, (_, block) in enumerate(indexed)]
