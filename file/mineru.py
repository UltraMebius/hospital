"""Normalize MinerU content-list exports into the parsing data contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .citations import extract_citations
from .document_order import classify_document_blocks, order_document_blocks
from .header_footer import filter_repeated_headers_footers
from .models import AssetType, BlockType, ContentBlock, ExtractedAsset, ParsedDocument
from .table_markdown import html_table_to_markdown


def _as_text_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    return tuple(str(item) for item in value if str(item).strip())


def _read_export(path: Path) -> dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8")
    parsed = json.loads(raw_text)
    if isinstance(parsed, list):
        export: dict[str, Any] = {"content_list_json": parsed}
    elif isinstance(parsed, dict):
        export = parsed
    else:
        raise ValueError(f"{path} must contain a MinerU content list or export object")
    content = export.get("content_list_json")
    if isinstance(content, str):
        content = json.loads(content)
    if not isinstance(content, list):
        raise ValueError(f"{path} does not contain a content_list_json array")
    export["content_list_json"] = content
    middle = export.get("middle_json")
    if isinstance(middle, str):
        middle = json.loads(middle)
    if not isinstance(middle, dict) and path.name.endswith("_content_list.json"):
        middle_path = path.with_name(path.name.replace("_content_list.json", "_middle.json"))
        if middle_path.is_file():
            candidate_middle = json.loads(middle_path.read_text(encoding="utf-8"))
            if isinstance(candidate_middle, dict):
                middle = candidate_middle
    export["middle_json"] = middle if isinstance(middle, dict) else {}
    return export


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


def _middle_visual_regions(
    export: dict[str, Any],
) -> dict[tuple[int, str], list[tuple[tuple[float, float, float, float], str]]]:
    """Collect MinerU visual regions by page and visual type."""

    middle = export.get("middle_json", {})
    pdf_info = middle.get("pdf_info", []) if isinstance(middle, dict) else []
    regions: dict[tuple[int, str], list[tuple[tuple[float, float, float, float], str]]] = {}
    for fallback_page, page_info in enumerate(pdf_info):
        if not isinstance(page_info, dict):
            continue
        page = int(page_info.get("page_idx", fallback_page)) + 1
        page_size = page_info.get("page_size")
        for collection in ("images", "charts"):
            visual_type = "image" if collection == "images" else "chart"
            for visual in page_info.get(collection, []):
                if not isinstance(visual, dict):
                    continue
                component_boxes = [
                    bbox
                    for component in visual.get("blocks", [])
                    if isinstance(component, dict)
                    and str(component.get("type", ""))
                    in {
                        "image_body",
                        "image_caption",
                        "image_footnote",
                        "chart_body",
                        "chart_caption",
                        "chart_footnote",
                    }
                    and (bbox := _as_bbox(component.get("bbox"))) is not None
                ]
                bbox = component_boxes[0] if component_boxes else _as_bbox(visual.get("bbox"))
                if bbox is None:
                    continue
                for component_bbox in component_boxes[1:]:
                    bbox = _union_bbox(bbox, component_bbox)
                coordinate_space = _middle_coordinate_space(bbox, page_size)
                regions.setdefault((page, visual_type), []).append((bbox, coordinate_space))
    return regions


def _middle_coordinate_space(bbox: tuple[float, float, float, float], page_size: object) -> str:
    if all(0.0 <= value <= 1.0 for value in bbox):
        return "normalized_1"
    if isinstance(page_size, (list, tuple)) and len(page_size) == 2:
        width, height = (float(value) for value in page_size)
        if bbox[2] <= width * 1.05 and bbox[3] <= height * 1.05:
            return "page"
    return "normalized_1000"


def _resolve_asset_source(export_path: Path, export: dict[str, Any], raw_path: str) -> Path | None:
    if not raw_path:
        return None
    candidates = [export_path.parent / raw_path]
    output_path = export.get("output_path")
    if isinstance(output_path, str) and output_path:
        candidates.append(Path(output_path) / raw_path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def normalize_mineru_export(
    export_path: Path,
    *,
    article_name: str | None = None,
    source_pdf: Path | None = None,
    header_footer_edge_blocks: int = 2,
    header_footer_repeat_ratio: float = 0.5,
    filter_headers_footers: bool = True,
) -> ParsedDocument:
    export_path = export_path.resolve()
    export = _read_export(export_path)
    article = article_name or export_path.stem
    if not article.strip() or article in {".", ".."} or "/" in article or "\\" in article:
        raise ValueError("article_name must be a single non-empty directory name")
    if source_pdf is None:
        candidate = export_path.with_suffix(".pdf")
        source_pdf = candidate if candidate.is_file() else None

    blocks: list[ContentBlock] = []
    assets: list[ExtractedAsset] = []
    middle_visuals = _middle_visual_regions(export)
    middle_visual_indices: dict[tuple[int, str], int] = {}
    image_count = 0
    table_count = 0
    for order, raw in enumerate(export["content_list_json"]):
        raw_type = str(raw.get("type", "text")).lower()
        page = int(raw.get("page_idx", 0)) + 1
        block_id = f"{article}:{order:05d}"
        bbox = _as_bbox(raw.get("bbox"))
        bbox_coordinate_space = "normalized_1000" if bbox is not None else None
        metadata = {
            key: value
            for key, value in raw.items()
            if key
            not in {
                "type",
                "text",
                "text_level",
                "page_idx",
                "img_path",
                "image_caption",
                "image_footnote",
                "chart_caption",
                "chart_footnote",
                "table_body",
                "table_caption",
                "table_footnote",
                "bbox",
            }
        }

        if raw_type in {"image", "chart"}:
            image_count += 1
            visual_key = (page, raw_type)
            visual_index = middle_visual_indices.get(visual_key, 0)
            page_visuals = middle_visuals.get(visual_key, [])
            if visual_index < len(page_visuals):
                bbox, bbox_coordinate_space = page_visuals[visual_index]
                middle_visual_indices[visual_key] = visual_index + 1
            raw_path = str(raw.get("img_path", ""))
            source = _resolve_asset_source(export_path, export, raw_path)
            suffix = source.suffix.lower() if source else Path(raw_path).suffix.lower()
            suffix = (
                suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"} else ".png"
            )
            output_file = f"image_{image_count:04d}{suffix}"
            asset_id = f"image-{image_count:04d}"
            caption_key = "chart_caption" if raw_type == "chart" else "image_caption"
            footnote_key = "chart_footnote" if raw_type == "chart" else "image_footnote"
            caption = _as_text_list(raw.get(caption_key))
            footnote = _as_text_list(raw.get(footnote_key))
            assets.append(
                ExtractedAsset(
                    id=asset_id,
                    page=page,
                    type=AssetType.IMAGE,
                    output_files=(output_file,),
                    source_path=source,
                    bbox=bbox,
                    caption=caption,
                    footnote=footnote,
                    metadata={
                        "mineru_path": raw_path,
                        "mineru_visual_type": raw_type,
                        "bbox_source": (
                            "middle_json_visual_union"
                            if visual_index < len(page_visuals)
                            else "content_list"
                        ),
                        "bbox_coordinate_space": bbox_coordinate_space,
                        "mineru_caption_in_bbox": bool(caption or footnote),
                    },
                )
            )
            blocks.append(
                ContentBlock(
                    id=block_id,
                    page=page,
                    order=order,
                    type=BlockType.IMAGE,
                    text="\n".join(caption),
                    bbox=bbox,
                    asset_paths=(output_file,),
                    metadata={**metadata, "asset_id": asset_id},
                )
            )
            continue

        if raw_type == "table":
            table_count += 1
            raw_path = str(raw.get("img_path", ""))
            source = _resolve_asset_source(export_path, export, raw_path)
            markdown_file = f"table_{table_count:04d}.md"
            output_files = [markdown_file]
            if source:
                suffix = source.suffix.lower() or ".png"
                output_files.append(f"table_{table_count:04d}{suffix}")
            asset_id = f"table-{table_count:04d}"
            caption = _as_text_list(raw.get("table_caption"))
            table_body = html_table_to_markdown(str(raw.get("table_body", "")))
            assets.append(
                ExtractedAsset(
                    id=asset_id,
                    page=page,
                    type=AssetType.TABLE,
                    output_files=tuple(output_files),
                    source_path=source,
                    bbox=bbox,
                    structured_content=table_body,
                    caption=caption,
                    footnote=_as_text_list(raw.get("table_footnote")),
                    metadata={
                        "mineru_path": raw_path,
                        "structured_format": "markdown",
                        "bbox_coordinate_space": bbox_coordinate_space,
                    },
                )
            )
            blocks.append(
                ContentBlock(
                    id=block_id,
                    page=page,
                    order=order,
                    type=BlockType.TABLE,
                    text=table_body,
                    bbox=bbox,
                    asset_paths=tuple(output_files),
                    metadata={
                        **metadata,
                        "asset_id": asset_id,
                        "caption": list(caption),
                        "structured_format": "markdown",
                    },
                )
            )
            continue

        if raw_type == "equation":
            block_type = BlockType.EQUATION
        elif raw.get("text_level") is not None:
            block_type = BlockType.TITLE
        else:
            block_type = BlockType.TEXT
        blocks.append(
            ContentBlock(
                id=block_id,
                page=page,
                order=order,
                type=block_type,
                text=str(raw.get("text", "")),
                level=raw.get("text_level"),
                bbox=bbox,
                metadata=metadata,
            )
        )

    blocks = classify_document_blocks(blocks, article_name=article)
    if filter_headers_footers:
        kept, removed = filter_repeated_headers_footers(
            blocks,
            edge_blocks=header_footer_edge_blocks,
            repeat_ratio=header_footer_repeat_ratio,
        )
    else:
        kept, removed = blocks, []
    kept = order_document_blocks(kept)
    citations = extract_citations(kept)
    return ParsedDocument(
        article_name=article,
        source_export=export_path,
        source_pdf=source_pdf.resolve() if source_pdf else None,
        blocks=tuple(kept),
        assets=tuple(assets),
        citations=tuple(citations),
        filtered_margins=tuple(removed),
    )
