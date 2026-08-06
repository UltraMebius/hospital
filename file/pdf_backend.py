"""Native PDF text, rendering, and embedded-image extraction."""

from __future__ import annotations

import contextlib
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from .table_markdown import extracted_table_to_markdown, rows_to_markdown

_REFERENCE_TOKEN_RE = re.compile(r"^[\s\d０-９\[\]［］()（）,，、.．\-–—~～*＊†‡]+$")
_REFERENCE_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"(?:[\[［(（]\s*)?\d{1,3}(?:\s*[,，、\-–—~～]\s*\d{1,3})*"
    r"(?:\s*[\]］)）])?"
    r"|[*＊†‡]+"
    r")\s*$"
)
_NOTE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:[【\[]\s*)?注(?:释)?(?:\s*[】\]])?\s*[:：]"
    r"|(?:[【\[]\s*)?(?:基金项目|基金资助|通信作者|作者简介|作者单位|"
    r"利益冲突|伦理声明|收稿日期|修回日期|DOI)(?:\s*[】\]])?\s*[:：]?)",
    flags=re.IGNORECASE,
)
_FIGURE_CAPTION_RE = re.compile(
    r"(?:^|[\s（(])(?:图\s*[A-Za-z]?\s*\d+|fig(?:ure)?\.?\s*[A-Za-z]?\s*\d+)",
    flags=re.IGNORECASE,
)
_TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:表|table)\s*[A-Za-z]?\s*\d+",
    flags=re.IGNORECASE,
)
_TABLE_NOTE_RE = re.compile(r"^\s*(?:注|note)\s*[:：]", flags=re.IGNORECASE)
_SUBSCRIPT_TRANSLATION = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_SPACED_SUBSCRIPT_TERM_RE = re.compile(
    r"(?P<first>[A-Za-z]+[₀-₉]+)\s+(?P<second>[A-Z]{1,4}[₀-₉]+)\s*"
    r"(?P<suffix>-[A-Za-z]+)"
)


def _as_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _union_bbox(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def _horizontal_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0]))


def _extend_table_note(
    blocks: list[tuple[tuple[float, float, float, float], str]],
    note_bbox: tuple[float, float, float, float],
    note_text: str,
    region_x0: float,
    region_x1: float,
    boundary_y: float,
) -> tuple[tuple[float, float, float, float], str]:
    """Attach tightly spaced continuation blocks to a table note."""

    used: set[int] = set()
    while True:
        candidates = [
            (index, bbox, text)
            for index, (bbox, text) in enumerate(blocks)
            if index not in used
            and note_bbox[3] <= bbox[1] < boundary_y
            and bbox[1] - note_bbox[3] <= 7.5
            and _horizontal_overlap(bbox, (region_x0, 0.0, region_x1, 1.0)) > 0
            and not _TABLE_CAPTION_RE.search(text)
        ]
        if not candidates:
            return note_bbox, note_text
        index, bbox, text = min(candidates, key=lambda item: (item[1][1], item[1][0]))
        used.add(index)
        note_bbox = _union_bbox(note_bbox, bbox)
        note_text = f"{note_text} {text}"


def _body_font_size(raw_blocks: list[dict[str, Any]]) -> float:
    """Estimate body size using a character-weighted upper quartile."""

    sizes: list[float] = []
    for block in raw_blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text", "")).strip()
                size = float(span.get("size", 0.0))
                if text and size > 0:
                    sizes.extend([size] * min(len(text), 20))
    if not sizes:
        return 0.0
    sizes.sort()
    return sizes[int((len(sizes) - 1) * 0.75)]


def _is_reference_run(spans: list[dict[str, Any]], body_font_size: float) -> bool:
    text = "".join(str(span.get("text", "")) for span in spans)
    if not _REFERENCE_MARKER_RE.fullmatch(text):
        return False
    sizes = [float(span.get("size", 0.0)) for span in spans if str(span.get("text", "")).strip()]
    if not sizes or body_font_size <= 0:
        return False
    bracketed = any(character in text for character in "[［]］")
    superscript = any(int(span.get("flags", 0)) & 1 for span in spans)
    return bracketed or superscript or max(sizes) <= body_font_size * 0.70


def _is_subscript_run(
    spans: list[dict[str, Any]],
    start: int,
    end: int,
    body_font_size: float,
) -> bool:
    """Recognize small, lowered formula digits such as the 2 in CHA2DS2-VASc."""

    marker = "".join(str(span.get("text", "")) for span in spans[start:end]).strip()
    if not marker or not re.fullmatch(r"[\d+\-=()]+", marker):
        return False
    previous = str(spans[start - 1].get("text", "")) if start > 0 else ""
    if not re.search(r"[A-Za-zα-ωΑ-Ω)]$", previous.rstrip()):
        return False

    marker_sizes = [float(span.get("size", 0.0)) for span in spans[start:end]]
    marker_origins = [
        float(origin[1])
        for span in spans[start:end]
        if isinstance((origin := span.get("origin")), (list, tuple)) and len(origin) >= 2
    ]
    if not marker_sizes or not marker_origins or body_font_size <= 0:
        return False
    if max(marker_sizes) > body_font_size * 0.78:
        return False

    neighbor_origins: list[float] = []
    neighbor_tops: list[float] = []
    for neighbor_index in (start - 1, end):
        if not 0 <= neighbor_index < len(spans):
            continue
        neighbor = spans[neighbor_index]
        origin = neighbor.get("origin")
        if (
            isinstance(origin, (list, tuple))
            and len(origin) >= 2
            and float(neighbor.get("size", 0.0)) >= body_font_size * 0.85
        ):
            neighbor_origins.append(float(origin[1]))
            bbox = neighbor.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                neighbor_tops.append(float(bbox[1]))
    marker_tops = [
        float(bbox[1])
        for span in spans[start:end]
        if isinstance((bbox := span.get("bbox")), (list, tuple)) and len(bbox) >= 4
    ]
    if not neighbor_origins or not neighbor_tops or not marker_tops:
        return False
    marker_baseline = sum(marker_origins) / len(marker_origins)
    neighbor_baseline = sum(neighbor_origins) / len(neighbor_origins)
    baseline_lowered = marker_baseline - neighbor_baseline >= max(0.8, body_font_size * 0.08)
    marker_top = sum(marker_tops) / len(marker_tops)
    neighbor_top = sum(neighbor_tops) / len(neighbor_tops)
    visibly_lowered = marker_top - neighbor_top >= max(1.5, body_font_size * 0.18)
    return baseline_lowered or visibly_lowered


def _normalize_scientific_terms(text: str) -> str:
    return _SPACED_SUBSCRIPT_TERM_RE.sub(
        lambda match: f"{match.group('first')}{match.group('second')}{match.group('suffix')}",
        text,
    )


def _is_formula_or_bibliography_number(marker: str, previous_text: str, next_text: str) -> bool:
    if any(character in marker for character in "[［]］"):
        return False
    previous = previous_text.rstrip()
    following = next_text.lstrip()
    if re.search(r"(?:/m|[A-Za-zΑ-ω])$", previous) and not re.match(r"^[,，]", following):
        return True
    return bool(re.search(r"\d$", previous) and re.match(r"^[:：]", following))


def _split_line(
    spans: list[dict[str, Any]], body_font_size: float
) -> list[tuple[str, tuple[float, float, float, float], str]]:
    """Split inline superscript references from surrounding sentence text."""

    candidate = [
        bool(_REFERENCE_TOKEN_RE.fullmatch(str(span.get("text", ""))))
        and (
            int(span.get("flags", 0)) & 1 != 0
            or float(span.get("size", 0.0)) <= body_font_size * 0.82
        )
        for span in spans
    ]
    roles = ["body"] * len(spans)
    texts = [str(span.get("text", "")) for span in spans]
    index = 0
    while index < len(spans):
        if not candidate[index]:
            index += 1
            continue
        end = index + 1
        while end < len(spans) and candidate[end]:
            end += 1
        if _is_subscript_run(spans, index, end, body_font_size):
            for subscript_index in range(index, end):
                texts[subscript_index] = texts[subscript_index].translate(_SUBSCRIPT_TRANSLATION)
        elif _is_reference_run(spans[index:end], body_font_size):
            roles[index:end] = ["page_end_reference"] * (end - index)
        index = end

    fragments: list[tuple[str, tuple[float, float, float, float], str]] = []
    for span, text, role in zip(spans, texts, roles, strict=True):
        bbox = _as_bbox(span.get("bbox"))
        if not text or bbox is None:
            continue
        if fragments and fragments[-1][2] == role:
            previous_text, previous_bbox, _ = fragments[-1]
            fragments[-1] = (
                previous_text + text,
                _union_bbox(previous_bbox, bbox),
                role,
            )
        else:
            fragments.append((text, bbox, role))
    return [(_normalize_scientific_terms(text), bbox, role) for text, bbox, role in fragments]


@dataclass(frozen=True)
class NativeTextBlock:
    page: int
    text: str
    bbox: tuple[float, float, float, float] | None = None
    reading_role: str = "body"


@dataclass(frozen=True)
class PdfImage:
    page: int
    data: bytes
    extension: str
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PdfTable:
    page: int
    bbox: tuple[float, float, float, float]
    markdown: str
    caption: str
    footnote: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PdfBackend(Protocol):
    def __enter__(self) -> PdfBackend: ...

    def __exit__(self, *_: object) -> None: ...

    @property
    def page_count(self) -> int: ...

    def extract_text_blocks(self, page: int) -> list[NativeTextBlock]: ...

    def page_size(self, page: int) -> tuple[float, float]: ...

    def render_page(self, page: int, dpi: int = 300) -> bytes: ...

    def render_region(
        self, page: int, bbox: tuple[float, float, float, float], dpi: int = 300
    ) -> bytes: ...

    def figure_region(
        self,
        page: int,
        bbox: tuple[float, float, float, float],
        captions: Sequence[str] = (),
    ) -> tuple[float, float, float, float]: ...

    def extract_images(self) -> list[PdfImage]: ...

    def extract_tables(self) -> list[PdfTable]: ...

    def close(self) -> None: ...


class PyMuPdfBackend:
    """PyMuPDF-backed implementation imported lazily at runtime."""

    def __init__(self, path: Path) -> None:
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError(
                "PyMuPDF is required for hybrid PDF parsing. "
                "Run: python -m pip install -r requirements.txt"
            ) from error
        self._pymupdf = pymupdf
        self._document = pymupdf.open(str(path))

    def __enter__(self) -> PyMuPdfBackend:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def page_count(self) -> int:
        return len(self._document)

    def extract_text_blocks(self, page: int) -> list[NativeTextBlock]:
        pdf_page = self._document[page - 1]
        raw_blocks = pdf_page.get_text("dict", sort=False).get("blocks", [])
        body_font_size = _body_font_size(raw_blocks)
        blocks: list[NativeTextBlock] = []
        for raw in raw_blocks:
            if raw.get("type") != 0:
                continue
            lines = raw.get("lines", [])
            raw_text = "\n".join(
                "".join(str(span.get("text", "")) for span in line.get("spans", []))
                for line in lines
            ).strip()
            if not raw_text:
                continue
            if _NOTE_PREFIX_RE.match(raw_text):
                blocks.append(
                    NativeTextBlock(
                        page=page,
                        text=raw_text,
                        bbox=_as_bbox(raw.get("bbox")),
                        reading_role="page_end_note",
                    )
                )
                continue

            fragments: list[tuple[str, tuple[float, float, float, float], str]] = []
            for line in lines:
                line_fragments = _split_line(line.get("spans", []), body_font_size)
                for text, bbox, role in line_fragments:
                    if fragments and fragments[-1][2] == role:
                        previous_text, previous_bbox, _ = fragments[-1]
                        fragments[-1] = (
                            f"{previous_text}\n{text}",
                            _union_bbox(previous_bbox, bbox),
                            role,
                        )
                    else:
                        fragments.append((text, bbox, role))
            blocks.extend(
                NativeTextBlock(page=page, text=text, bbox=bbox, reading_role=role)
                for text, bbox, role in fragments
                if text.strip()
            )
        adjusted: list[NativeTextBlock] = []
        for index, block in enumerate(blocks):
            if block.reading_role != "page_end_reference":
                adjusted.append(block)
                continue
            previous_text = next(
                (
                    candidate.text
                    for candidate in reversed(blocks[:index])
                    if candidate.reading_role == "body"
                ),
                "",
            )
            next_text = next(
                (
                    candidate.text
                    for candidate in blocks[index + 1 :]
                    if candidate.reading_role == "body"
                ),
                "",
            )
            if _is_formula_or_bibliography_number(block.text, previous_text, next_text):
                block = replace(block, reading_role="body")
            adjusted.append(block)
        return adjusted

    def page_size(self, page: int) -> tuple[float, float]:
        rectangle = self._document[page - 1].rect
        return float(rectangle.width), float(rectangle.height)

    def render_page(self, page: int, dpi: int = 300) -> bytes:
        pixmap = self._document[page - 1].get_pixmap(dpi=dpi, alpha=False)
        return pixmap.tobytes("png")

    def render_region(
        self,
        page: int,
        bbox: tuple[float, float, float, float],
        dpi: int = 300,
    ) -> bytes:
        clip = self._pymupdf.Rect(*bbox)
        if clip.is_empty or clip.is_infinite:
            raise ValueError(f"invalid PDF crop bbox on page {page}: {bbox}")
        pixmap = self._document[page - 1].get_pixmap(
            dpi=dpi,
            alpha=False,
            clip=clip,
        )
        return pixmap.tobytes("png")

    def figure_region(
        self,
        page: int,
        bbox: tuple[float, float, float, float],
        captions: Sequence[str] = (),
    ) -> tuple[float, float, float, float]:
        """Extend a figure bbox to include its nearest labelled caption."""

        pdf_page = self._document[page - 1]
        page_rect = pdf_page.rect
        provided = [re.sub(r"\s+", "", item).casefold() for item in captions if item.strip()]
        candidates: list[tuple[float, tuple[float, float, float, float], str, bool]] = []
        figure_x0, figure_y0, figure_x1, figure_y1 = bbox
        figure_center = (figure_x0 + figure_x1) / 2
        figure_width = figure_x1 - figure_x0
        for raw_block in pdf_page.get_text("blocks", sort=False):
            if len(raw_block) < 5:
                continue
            text = str(raw_block[4]).strip()
            if not text:
                continue
            block_bbox = tuple(float(value) for value in raw_block[:4])
            block_x0, block_y0, block_x1, block_y1 = block_bbox
            compact = re.sub(r"\s+", "", text).casefold()
            labelled = bool(_FIGURE_CAPTION_RE.search(text))
            provided_match = any(
                (len(compact) >= 4 and compact in caption)
                or (len(caption) >= 4 and caption in compact)
                for caption in provided
            )
            if not labelled and not provided_match:
                continue

            if block_y0 >= figure_y1:
                distance = block_y0 - figure_y1
                if distance > 110:
                    continue
                position_penalty = 0.0
            elif block_y1 <= figure_y0:
                distance = figure_y0 - block_y1
                if distance > 70:
                    continue
                position_penalty = 25.0
            else:
                distance = 0.0
                position_penalty = 10.0

            horizontal_overlap = max(
                0.0,
                min(figure_x1, block_x1) - max(figure_x0, block_x0),
            )
            block_center = (block_x0 + block_x1) / 2
            if horizontal_overlap <= 0 and abs(block_center - figure_center) > max(
                80.0, figure_width * 0.75
            ):
                continue
            score = distance + position_penalty + (0.0 if labelled else 8.0)
            candidates.append((score, block_bbox, compact, provided_match))

        if not candidates:
            return bbox
        candidates.sort(key=lambda item: item[0])
        _, caption_bbox, _, _ = candidates[0]
        # MinerU captions can be split into adjacent PDF text blocks. Include only
        # blocks that also match the supplied caption and remain close to the label.
        for _, candidate_bbox, _, provided_match in candidates[1:]:
            if not provided_match:
                continue
            vertical_gap = max(
                0.0,
                candidate_bbox[1] - caption_bbox[3],
                caption_bbox[1] - candidate_bbox[3],
            )
            if vertical_gap <= 40:
                caption_bbox = _union_bbox(caption_bbox, candidate_bbox)

        region = _union_bbox(bbox, caption_bbox)
        return (
            max(0.0, region[0]),
            max(0.0, region[1]),
            min(float(page_rect.width), region[2]),
            min(float(page_rect.height), region[3]),
        )

    def extract_images(self) -> list[PdfImage]:
        images: list[PdfImage] = []
        seen_xrefs: set[int] = set()
        for page_index, page in enumerate(self._document, start=1):
            for image in page.get_image_info(xrefs=True):
                width = int(image.get("width", 0))
                height = int(image.get("height", 0))
                if min(width, height) < 32 or width * height < 4096:
                    continue
                xref = int(image.get("xref", 0))
                bbox = _as_bbox(image.get("bbox"))
                if bbox is None:
                    continue
                if xref > 0:
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    extracted = self._document.extract_image(xref)
                    data = extracted.get("image")
                    if not isinstance(data, bytes):
                        continue
                    extension = str(extracted.get("ext", "png")).lower()
                    source = "pdf_embedded_image"
                else:
                    clip = self._pymupdf.Rect(*bbox)
                    pixmap = page.get_pixmap(dpi=450, alpha=False, clip=clip)
                    data = pixmap.tobytes("png")
                    extension = "png"
                    source = "pdf_inline_image_render"
                images.append(
                    PdfImage(
                        page=page_index,
                        data=data,
                        extension=extension,
                        bbox=bbox,
                        metadata={
                            "source": source,
                            "xref": xref,
                            "width": width,
                            "height": height,
                            "bbox": list(bbox),
                        },
                    )
                )
        return images

    def extract_tables(self) -> list[PdfTable]:
        """Extract labelled tables from their title down through the note block."""

        tables: list[PdfTable] = []
        for page_number, page in enumerate(self._document, start=1):
            raw_blocks = [
                (tuple(float(value) for value in block[:4]), " ".join(str(block[4]).split()))
                for block in page.get_text("blocks", sort=True)
                if len(block) >= 5
                and (len(block) < 7 or int(block[6]) == 0)
                and str(block[4]).strip()
            ]
            captions = [block for block in raw_blocks if _TABLE_CAPTION_RE.search(block[1])]
            for caption_bbox, caption in captions:
                page_width = float(page.rect.width)
                midpoint = page_width / 2
                caption_width = caption_bbox[2] - caption_bbox[0]
                if caption_width >= page_width * 0.42:
                    region_x0, region_x1 = 30.0, page_width - 30.0
                    region_column = "full"
                elif (caption_bbox[0] + caption_bbox[2]) / 2 < midpoint:
                    region_x0, region_x1 = 30.0, midpoint - 4.0
                    region_column = "left"
                else:
                    region_x0, region_x1 = midpoint + 4.0, page_width - 30.0
                    region_column = "right"

                next_caption_y = min(
                    (
                        other_bbox[1]
                        for other_bbox, _ in captions
                        if other_bbox[1] > caption_bbox[3]
                        and _horizontal_overlap(other_bbox, (region_x0, 0, region_x1, 1)) > 0
                    ),
                    default=float(page.rect.height),
                )
                notes = [
                    block
                    for block in raw_blocks
                    if caption_bbox[3] < block[0][1] < next_caption_y
                    and _TABLE_NOTE_RE.search(block[1])
                    and _horizontal_overlap(block[0], (region_x0, 0, region_x1, 1)) > 0
                ]
                if not notes:
                    continue
                note_bbox, note_text = notes[0]
                note_bbox, note_text = _extend_table_note(
                    raw_blocks,
                    note_bbox,
                    note_text,
                    region_x0,
                    region_x1,
                    next_caption_y,
                )
                content_clip = (
                    region_x0,
                    caption_bbox[3] + 1.0,
                    region_x1,
                    note_bbox[1] - 1.0,
                )
                markdown = self._table_markdown(page, raw_blocks, content_clip)
                if not markdown.strip():
                    continue
                region_bbox = (
                    region_x0,
                    max(0.0, caption_bbox[1]),
                    region_x1,
                    min(float(page.rect.height), note_bbox[3]),
                )
                structured = f"**{caption}**\n\n{markdown}\n{note_text}\n"
                tables.append(
                    PdfTable(
                        page=page_number,
                        bbox=region_bbox,
                        markdown=structured,
                        caption=caption,
                        footnote=note_text,
                        metadata={
                            "source": "native_pdf_table_region",
                            "region_column": region_column,
                            "caption_bbox": list(caption_bbox),
                            "note_bbox": list(note_bbox),
                        },
                    )
                )
        return tables

    def _table_markdown(
        self,
        page: Any,
        raw_blocks: list[tuple[tuple[float, float, float, float], str]],
        clip: tuple[float, float, float, float],
    ) -> str:
        with contextlib.redirect_stdout(io.StringIO()):
            found = page.find_tables(
                clip=clip,
                vertical_strategy="text",
                horizontal_strategy="text",
            ).tables
        if found:
            best = max(found, key=lambda table: table.row_count * table.col_count)
            markdown = extracted_table_to_markdown(best.extract())
            if markdown.strip():
                return markdown

        fallback_rows = [["表格内容"]]
        fallback_rows.extend(
            [text]
            for bbox, text in raw_blocks
            if bbox[1] >= clip[1] and bbox[3] <= clip[3] and _horizontal_overlap(bbox, clip) > 0
        )
        return rows_to_markdown(fallback_rows) if len(fallback_rows) > 1 else ""

    def close(self) -> None:
        self._document.close()
