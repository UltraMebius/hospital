"""Hybrid PDF parsing with page-level native-text and OCR fallback."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from .citations import extract_citations
from .document_order import classify_document_blocks, order_document_blocks
from .header_footer import filter_repeated_headers_footers
from .mineru import normalize_mineru_export
from .models import AssetType, BlockType, ContentBlock, ExtractedAsset, ParsedDocument
from .ocr import OcrEngine
from .pdf_backend import NativeTextBlock, PdfBackend, PyMuPdfBackend
from .reading_order import detect_body_columns, order_page_blocks
from .text_quality import TextQuality, assess_text_quality

PdfBackendFactory = Callable[[Path], PdfBackend]
_TEXT_TYPES = frozenset({BlockType.TEXT, BlockType.TITLE})


def _normalized_crop_bbox(
    bbox: tuple[float, float, float, float],
    page_size: tuple[float, float],
    *,
    padding: float = 14.0,
    coordinate_space: str | None = None,
) -> tuple[float, float, float, float] | None:
    """Convert MinerU/PDF coordinates to PDF points and add padding."""

    page_width, page_height = page_size
    if page_width <= 0 or page_height <= 0:
        return None
    x0, y0, x1, y1 = bbox
    if coordinate_space == "normalized_1000":
        x0, x1 = x0 * page_width / 1000, x1 * page_width / 1000
        y0, y1 = y0 * page_height / 1000, y1 * page_height / 1000
    elif coordinate_space == "normalized_1":
        x0, x1 = x0 * page_width, x1 * page_width
        y0, y1 = y0 * page_height, y1 * page_height
    elif coordinate_space not in {None, "page"}:
        return None
    elif coordinate_space is None and (x1 > page_width * 1.05 or y1 > page_height * 1.05):
        if 0 <= x0 < x1 <= 1100 and 0 <= y0 < y1 <= 1100:
            x0, x1 = x0 * page_width / 1000, x1 * page_width / 1000
            y0, y1 = y0 * page_height / 1000, y1 * page_height / 1000
        else:
            return None
    x0 = max(0.0, x0 - padding)
    y0 = max(0.0, y0 - padding)
    x1 = min(page_width, x1 + padding)
    y1 = min(page_height, y1 + padding)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _joined_text(blocks: Sequence[ContentBlock]) -> str:
    return "\n".join(block.text for block in blocks if block.type in _TEXT_TYPES)


def _native_text(blocks: Sequence[NativeTextBlock]) -> str:
    return "\n".join(block.text for block in blocks)


def _replacement_blocks(
    article_name: str,
    page: int,
    source: str,
    native_blocks: Sequence[NativeTextBlock],
    ocr_text: str | None,
) -> list[ContentBlock]:
    if source == "native_pdf":
        return [
            ContentBlock(
                id=f"{article_name}:native:{page}:{index:04d}",
                page=page,
                order=index,
                type=BlockType.TEXT,
                text=block.text,
                bbox=block.bbox,
                metadata={
                    "text_source": "native_pdf",
                    "reading_role": block.reading_role,
                },
            )
            for index, block in enumerate(native_blocks)
        ]
    if source == "ocr" and ocr_text:
        return [
            ContentBlock(
                id=f"{article_name}:ocr:{page}:0000",
                page=page,
                order=0,
                type=BlockType.TEXT,
                text=ocr_text,
                metadata={"text_source": "ocr"},
            )
        ]
    return []


def _replace_text_blocks(
    original: Sequence[ContentBlock], replacements: Sequence[ContentBlock]
) -> list[ContentBlock]:
    first_text = next(
        (index for index, block in enumerate(original) if block.type in _TEXT_TYPES),
        0,
    )
    result: list[ContentBlock] = []
    inserted = False
    for index, block in enumerate(original):
        if index == first_text:
            result.extend(replacements)
            inserted = True
        if block.type not in _TEXT_TYPES:
            result.append(block)
    if not inserted:
        result[0:0] = replacements
    return result


def _quality(
    text: str,
    *,
    minimum_visible_characters: int,
    minimum_cjk_characters: int,
    maximum_suspicious_ratio: float,
) -> TextQuality:
    return assess_text_quality(
        text,
        minimum_visible_characters=minimum_visible_characters,
        minimum_cjk_characters=minimum_cjk_characters,
        maximum_suspicious_ratio=maximum_suspicious_ratio,
    )


def _best_source(candidate_quality: dict[str, TextQuality]) -> str:
    return max(
        candidate_quality,
        key=lambda item: (
            candidate_quality[item].acceptable,
            candidate_quality[item].cjk_characters,
            candidate_quality[item].score,
        ),
    )


def build_hybrid_document(
    pdf_path: Path,
    *,
    mineru_export: Path | None = None,
    article_name: str | None = None,
    ocr_engine: OcrEngine | None = None,
    pdf_backend_factory: PdfBackendFactory = PyMuPdfBackend,
    render_dpi: int = 300,
    minimum_visible_characters: int = 20,
    minimum_cjk_characters: int = 4,
    maximum_suspicious_ratio: float = 0.05,
    ocr_figures: bool = False,
    header_footer_edge_blocks: int = 2,
    header_footer_repeat_ratio: float = 0.5,
) -> ParsedDocument:
    """Build one normalized document by selecting the best text source per page."""

    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    article = article_name or pdf_path.stem
    if not article.strip() or article in {".", ".."} or "/" in article or "\\" in article:
        raise ValueError("article_name must be a single non-empty directory name")

    if mineru_export:
        mineru_document = normalize_mineru_export(
            mineru_export,
            article_name=article,
            source_pdf=pdf_path,
            filter_headers_footers=False,
        )
        mineru_blocks = list(mineru_document.blocks)
        assets = list(mineru_document.assets)
        source_export = mineru_document.source_export
    else:
        mineru_blocks = []
        assets = []
        source_export = None

    mineru_by_page: dict[int, list[ContentBlock]] = defaultdict(list)
    for block in mineru_blocks:
        mineru_by_page[block.page].append(block)

    final_blocks: list[ContentBlock] = []
    page_sources: dict[str, str] = {}
    page_quality: dict[str, dict[str, object]] = {}
    unresolved_pages: list[int] = []
    native_table_count = 0
    table_extraction_source = "mineru"
    incomplete_mineru_images = [
        asset.id for asset in assets if asset.type is AssetType.IMAGE and asset.bbox is None
    ]
    if incomplete_mineru_images:
        raise ValueError(
            "MinerU image blocks require bbox coordinates for cropping; "
            f"incomplete assets: {', '.join(incomplete_mineru_images)}. "
            "Export the complete MinerU content_list.json/middle.json and images directory."
        )

    with pdf_backend_factory(pdf_path) as pdf:
        native_by_page = {
            page: pdf.extract_text_blocks(page) for page in range(1, pdf.page_count + 1)
        }
        page_sizes = {page: pdf.page_size(page) for page in range(1, pdf.page_count + 1)}
        layout = detect_body_columns(native_by_page, page_sizes)
        native_page_one = order_page_blocks(
            native_by_page[1],
            page_sizes[1][0],
            columns=layout.body_columns,
        )
        native_page_one_content = _replacement_blocks(
            article,
            1,
            "native_pdf",
            native_page_one,
            None,
        )
        native_page_one_content = classify_document_blocks(
            native_page_one_content,
            article_name=article,
        )
        native_first_page_header = [
            replace(
                block,
                id=f"{block.id}:preserved-header",
                metadata={
                    **block.metadata,
                    "forced_document_role": "first_page_header",
                },
            )
            for block in native_page_one_content
            if block.metadata.get("document_role") == "first_page_header"
        ]
        for page in range(1, pdf.page_count + 1):
            page_mineru = sorted(mineru_by_page.get(page, []), key=lambda block: block.order)
            native_blocks = order_page_blocks(
                native_by_page[page],
                page_sizes[page][0],
                columns=layout.body_columns,
            )
            candidate_text = {
                "mineru": _joined_text(page_mineru),
                "native_pdf": _native_text(native_blocks),
            }
            candidate_quality = {
                source: _quality(
                    text,
                    minimum_visible_characters=minimum_visible_characters,
                    minimum_cjk_characters=minimum_cjk_characters,
                    maximum_suspicious_ratio=maximum_suspicious_ratio,
                )
                for source, text in candidate_text.items()
            }
            source = _best_source(candidate_quality)
            ocr_text: str | None = None

            if not candidate_quality[source].acceptable and ocr_engine is not None:
                ocr_text = ocr_engine.recognize_page(pdf.render_page(page, render_dpi), page)
                candidate_text["ocr"] = ocr_text
                candidate_quality["ocr"] = _quality(
                    ocr_text,
                    minimum_visible_characters=minimum_visible_characters,
                    minimum_cjk_characters=minimum_cjk_characters,
                    maximum_suspicious_ratio=maximum_suspicious_ratio,
                )
                source = _best_source(candidate_quality)

            chosen_quality = candidate_quality[source]
            if not chosen_quality.acceptable:
                unresolved_pages.append(page)
            page_sources[str(page)] = source
            page_quality[str(page)] = {
                name: quality.to_dict() for name, quality in candidate_quality.items()
            }

            if source == "mineru" and page_mineru:
                page_blocks = page_mineru
                if page == 1:
                    mineru_text = re.sub(r"\s+", "", _joined_text(page_mineru))
                    page_blocks = [*page_blocks]
                    page_blocks.extend(
                        block
                        for block in native_first_page_header
                        if re.sub(r"\s+", "", block.text) not in mineru_text
                    )
            else:
                replacements = _replacement_blocks(
                    article,
                    page,
                    source,
                    native_blocks,
                    ocr_text,
                )
                page_blocks = _replace_text_blocks(page_mineru, replacements)
            final_blocks.extend(page_blocks)

        native_tables = pdf.extract_tables()
        mineru_table_count = sum(asset.type is AssetType.TABLE for asset in assets)
        if native_tables and len(native_tables) >= mineru_table_count:
            native_table_count = len(native_tables)
            table_extraction_source = "native_pdf_title_to_note"
            assets = [asset for asset in assets if asset.type is not AssetType.TABLE]
            final_blocks = [block for block in final_blocks if block.type is not BlockType.TABLE]
            for table_index, table in enumerate(native_tables, start=1):
                markdown_file = f"table_{table_index:04d}.md"
                image_file = f"table_{table_index:04d}.png"
                asset_id = f"native-table-{table_index:04d}"
                crop_dpi = max(render_dpi, 450)
                assets.append(
                    ExtractedAsset(
                        id=asset_id,
                        page=table.page,
                        type=AssetType.TABLE,
                        output_files=(markdown_file, image_file),
                        binary_content=pdf.render_region(table.page, table.bbox, crop_dpi),
                        bbox=table.bbox,
                        structured_content=table.markdown,
                        caption=(table.caption,),
                        footnote=(table.footnote,),
                        metadata={
                            **table.metadata,
                            "structured_format": "markdown",
                            "crop_dpi": crop_dpi,
                            "normalized_bbox": list(table.bbox),
                            "range_rule": "table_caption_to_note_end",
                        },
                    )
                )
                page_orders = [block.order for block in final_blocks if block.page == table.page]
                final_blocks.append(
                    ContentBlock(
                        id=f"{article}:{asset_id}",
                        page=table.page,
                        order=max(page_orders, default=0) + table_index,
                        type=BlockType.TABLE,
                        text=table.markdown,
                        bbox=table.bbox,
                        asset_paths=(markdown_file, image_file),
                        metadata={
                            "asset_id": asset_id,
                            "caption": [table.caption],
                            "structured_format": "markdown",
                            "range_rule": "table_caption_to_note_end",
                        },
                    )
                )

        mapped_asset_files: dict[str, tuple[str, ...]] = {}
        cropped_assets: list[ExtractedAsset] = []
        for asset in assets:
            if asset.type is AssetType.IMAGE:
                if asset.bbox is None:
                    raise AssertionError("MinerU image bbox validation was bypassed")
                crop_bbox = _normalized_crop_bbox(
                    asset.bbox,
                    page_sizes[asset.page],
                    padding=4.0,
                    coordinate_space=asset.metadata.get("bbox_coordinate_space"),
                )
                if crop_bbox is None:
                    raise ValueError(
                        f"invalid MinerU bbox for {asset.id} on page {asset.page}: {asset.bbox}"
                    )
                crop_dpi = max(render_dpi, 450)
                output_file = f"{Path(asset.output_files[-1]).stem}.png"
                asset = replace(
                    asset,
                    source_path=None,
                    bbox=crop_bbox,
                    output_files=(output_file,),
                    binary_content=pdf.render_region(asset.page, crop_bbox, crop_dpi),
                    metadata={
                        **asset.metadata,
                        "source": "mineru_bbox_pdf_render",
                        "crop_dpi": crop_dpi,
                        "normalized_bbox": list(crop_bbox),
                        "caption_included": bool(asset.metadata.get("mineru_caption_in_bbox")),
                        "crop_authority": "mineru",
                    },
                )
                mapped_asset_files[asset.id] = asset.output_files
            if (
                asset.type is AssetType.TABLE
                and asset.source_path is None
                and asset.binary_content is None
                and asset.bbox is not None
            ):
                crop_bbox = _normalized_crop_bbox(
                    asset.bbox,
                    page_sizes[asset.page],
                    coordinate_space=asset.metadata.get("bbox_coordinate_space"),
                )
                if crop_bbox is not None:
                    output_files = (*asset.output_files, f"{Path(asset.output_files[0]).stem}.png")
                    crop_dpi = max(render_dpi, 450)
                    asset = replace(
                        asset,
                        bbox=crop_bbox,
                        output_files=output_files,
                        binary_content=pdf.render_region(asset.page, crop_bbox, crop_dpi),
                        metadata={
                            **asset.metadata,
                            "source": "pdf_region_crop",
                            "crop_dpi": crop_dpi,
                            "normalized_bbox": list(crop_bbox),
                        },
                    )
            cropped_assets.append(asset)
        assets = cropped_assets
        final_blocks = [
            replace(block, asset_paths=mapped_asset_files[block.metadata["asset_id"]])
            if block.metadata.get("asset_id") in mapped_asset_files
            else block
            for block in final_blocks
        ]

    if ocr_figures and ocr_engine is not None:
        assets_with_ocr: list[ExtractedAsset] = []
        for asset in assets:
            image_bytes = asset.binary_content
            if image_bytes is None and asset.source_path and asset.source_path.is_file():
                image_bytes = asset.source_path.read_bytes()
            if asset.type is AssetType.IMAGE and image_bytes:
                ocr_text = ocr_engine.recognize_page(image_bytes, asset.page)
                asset = replace(
                    asset,
                    metadata={
                        **asset.metadata,
                        "ocr_engine": ocr_engine.name,
                        "ocr_text": ocr_text,
                    },
                )
            assets_with_ocr.append(asset)
        assets = assets_with_ocr

    ordered = sorted(final_blocks, key=lambda block: (block.page, block.order))
    ordered = classify_document_blocks(ordered, article_name=article)
    ordered = [replace(block, order=index) for index, block in enumerate(ordered)]
    kept, removed = filter_repeated_headers_footers(
        ordered,
        edge_blocks=header_footer_edge_blocks,
        repeat_ratio=header_footer_repeat_ratio,
    )
    kept = order_document_blocks(kept)
    citations = extract_citations(kept)
    return ParsedDocument(
        article_name=article,
        source_export=source_export,
        source_pdf=pdf_path,
        blocks=tuple(kept),
        assets=tuple(assets),
        citations=tuple(citations),
        filtered_margins=tuple(removed),
        metadata={
            "parsing_mode": "hybrid",
            "page_sources": page_sources,
            "page_text_quality": page_quality,
            "unresolved_text_pages": unresolved_pages,
            "ocr_engine": ocr_engine.name if ocr_engine else None,
            "render_dpi": render_dpi,
            "ocr_figures": ocr_figures,
            "layout": layout.to_dict(),
            "figure_extraction_source": "mineru",
            "table_extraction_source": table_extraction_source,
            "native_table_count": native_table_count,
        },
    )
