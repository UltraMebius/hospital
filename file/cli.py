"""Command-line interface for document parsing and normalization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ocr import TesseractOcrEngine
from .pipeline import parse_hybrid_pdf, parse_mineru_export


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--result-root", type=Path, default=Path("result"))
    parser.add_argument("--article-name")
    parser.add_argument("--header-footer-edge-blocks", type=int, default=2)
    parser.add_argument("--header-footer-repeat-ratio", type=float, default=0.5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hospital-file")
    commands = parser.add_subparsers(dest="command", required=True)

    normalize = commands.add_parser(
        "normalize-mineru", help="normalize one MinerU export or a directory of exports"
    )
    normalize.add_argument("input", type=Path)
    _add_output_arguments(normalize)

    hybrid = commands.add_parser(
        "parse-hybrid",
        help="parse PDF files with MinerU/native-text/OCR page-level fallback",
    )
    hybrid.add_argument("input", type=Path, help="one PDF file or a directory of PDFs")
    hybrid.add_argument("--mineru-export", type=Path)
    hybrid.add_argument("--mineru-export-dir", type=Path)
    hybrid.add_argument("--ocr-engine", choices=("none", "tesseract"), default="none")
    hybrid.add_argument("--ocr-language", default="chi_sim+eng")
    hybrid.add_argument("--ocr-figures", action="store_true")
    hybrid.add_argument("--tesseract-executable", default="tesseract")
    hybrid.add_argument("--render-dpi", type=int, default=300)
    hybrid.add_argument("--minimum-visible-characters", type=int, default=20)
    hybrid.add_argument("--minimum-cjk-characters", type=int, default=4)
    hybrid.add_argument("--maximum-suspicious-ratio", type=float, default=0.05)
    hybrid.add_argument("--require-complete-text", action="store_true")
    _add_output_arguments(hybrid)
    return parser


def _normalization_inputs(path: Path) -> list[Path]:
    if not path.is_dir():
        return [path]
    return sorted([*path.glob("*.jsonl"), *path.glob("*_content_list.json")])


def _pdf_inputs(path: Path) -> list[Path]:
    return sorted(path.glob("*.pdf")) if path.is_dir() else [path]


def _paired_export(pdf_path: Path, args: argparse.Namespace, total: int) -> Path | None:
    if args.mineru_export:
        if total != 1:
            raise ValueError("--mineru-export can only be used with one PDF")
        return args.mineru_export
    export_dir = args.mineru_export_dir or pdf_path.parent
    candidates = (
        export_dir / f"{pdf_path.stem}_content_list.json",
        export_dir / f"{pdf_path.stem}.jsonl",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _ocr_engine(args: argparse.Namespace) -> TesseractOcrEngine | None:
    if args.ocr_engine == "none":
        return None
    return TesseractOcrEngine(
        executable=args.tesseract_executable,
        languages=args.ocr_language,
    )


def _normalize_command(args: argparse.Namespace) -> list[dict[str, str]]:
    inputs = _normalization_inputs(args.input)
    if not inputs:
        raise ValueError(f"no MinerU content-list exports found under {args.input}")
    if args.article_name and len(inputs) != 1:
        raise ValueError("--article-name can only be used with one input file")
    outputs = []
    for export_path in inputs:
        paths = parse_mineru_export(
            export_path,
            args.result_root,
            article_name=args.article_name,
            header_footer_edge_blocks=args.header_footer_edge_blocks,
            header_footer_repeat_ratio=args.header_footer_repeat_ratio,
        )
        outputs.append({key: str(value) for key, value in paths.items()})
    return outputs


def _hybrid_command(args: argparse.Namespace) -> list[dict[str, str]]:
    inputs = _pdf_inputs(args.input)
    if not inputs:
        raise ValueError(f"no PDF files found under {args.input}")
    if args.article_name and len(inputs) != 1:
        raise ValueError("--article-name can only be used with one PDF")
    engine = _ocr_engine(args)
    outputs = []
    for pdf_path in inputs:
        paths = parse_hybrid_pdf(
            pdf_path,
            args.result_root,
            mineru_export=_paired_export(pdf_path, args, len(inputs)),
            article_name=args.article_name,
            ocr_engine=engine,
            render_dpi=args.render_dpi,
            minimum_visible_characters=args.minimum_visible_characters,
            minimum_cjk_characters=args.minimum_cjk_characters,
            maximum_suspicious_ratio=args.maximum_suspicious_ratio,
            ocr_figures=args.ocr_figures,
            header_footer_edge_blocks=args.header_footer_edge_blocks,
            header_footer_repeat_ratio=args.header_footer_repeat_ratio,
        )
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        unresolved = manifest.get("unresolved_text_pages", [])
        if args.require_complete_text and unresolved:
            raise RuntimeError(
                f"{pdf_path} still has unresolved text pages after fallback: {unresolved}"
            )
        outputs.append({key: str(value) for key, value in paths.items()})
    return outputs


def main() -> int:
    args = build_parser().parse_args()
    outputs = (
        _normalize_command(args) if args.command == "normalize-mineru" else _hybrid_command(args)
    )
    print(json.dumps({"documents": len(outputs), "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
