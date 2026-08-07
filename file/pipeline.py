"""Public document parsing entry points."""

from __future__ import annotations

from pathlib import Path

from .hybrid import PdfBackendFactory, build_hybrid_document
from .mineru import normalize_mineru_export
from .ocr import OcrEngine
from .output import write_parsed_document
from .pdf_backend import PyMuPdfBackend


def parse_mineru_export(
    export_path: Path,
    result_root: Path = Path("result"),
    *,
    article_name: str | None = None,
    source_pdf: Path | None = None,
    header_footer_edge_blocks: int = 2,
    header_footer_repeat_ratio: float = 0.5,
) -> dict[str, Path]:
    document = normalize_mineru_export(
        export_path,
        article_name=article_name,
        source_pdf=source_pdf,
        header_footer_edge_blocks=header_footer_edge_blocks,
        header_footer_repeat_ratio=header_footer_repeat_ratio,
    )
    return write_parsed_document(document, result_root)


def parse_hybrid_pdf(
    pdf_path: Path,
    result_root: Path = Path("result"),
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
) -> dict[str, Path]:
    document = build_hybrid_document(
        pdf_path,
        mineru_export=mineru_export,
        article_name=article_name,
        ocr_engine=ocr_engine,
        pdf_backend_factory=pdf_backend_factory,
        render_dpi=render_dpi,
        minimum_visible_characters=minimum_visible_characters,
        minimum_cjk_characters=minimum_cjk_characters,
        maximum_suspicious_ratio=maximum_suspicious_ratio,
        ocr_figures=ocr_figures,
        header_footer_edge_blocks=header_footer_edge_blocks,
        header_footer_repeat_ratio=header_footer_repeat_ratio,
    )
    return write_parsed_document(document, result_root)
