"""Write normalized parsing results to the required directory structure."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .models import AssetType, ParsedDocument


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _remove_previous_asset_files(figures_dir: Path, assets_path: Path) -> None:
    """Remove only files recorded by the preceding generated asset manifest."""

    if not assets_path.is_file():
        return
    names: set[str] = set()
    for line in assets_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        written = record.get("written_files", [])
        if isinstance(written, list):
            names.update(str(name) for name in written)
    resolved_dir = figures_dir.resolve()
    for name in names:
        target = figures_dir / name
        if target.parent.resolve() != resolved_dir or target.is_symlink():
            continue
        if target.is_file():
            target.unlink()


def write_parsed_document(document: ParsedDocument, result_root: Path) -> dict[str, Path]:
    jsonl_dir = result_root / "jsonl" / document.article_name
    figures_dir = result_root / "figures" / document.article_name
    citations_dir = result_root / "citations" / document.article_name
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    citations_dir.mkdir(parents=True, exist_ok=True)

    content_path = jsonl_dir / "content.jsonl"
    margins_path = jsonl_dir / "filtered_headers_footers.jsonl"
    citations_path = citations_dir / "citations.jsonl"
    manifest_path = jsonl_dir / "manifest.json"
    assets_path = figures_dir / "assets.jsonl"

    _write_jsonl(content_path, [block.to_dict() for block in document.blocks])
    _write_jsonl(margins_path, [block.to_dict() for block in document.filtered_margins])
    _write_jsonl(citations_path, [citation.to_dict() for citation in document.citations])
    _remove_previous_asset_files(figures_dir, assets_path)

    missing_assets: list[str] = []
    asset_records: list[dict[str, Any]] = []
    for asset in document.assets:
        written_files: list[str] = []
        if asset.type is AssetType.TABLE and asset.structured_content is not None:
            (figures_dir / asset.output_files[0]).write_text(
                asset.structured_content, encoding="utf-8", newline="\n"
            )
            written_files.append(asset.output_files[0])
        copied = False
        if asset.source_path and asset.source_path.is_file():
            target_name = asset.output_files[-1]
            shutil.copy2(asset.source_path, figures_dir / target_name)
            copied = True
            written_files.append(target_name)
        elif asset.binary_content is not None:
            target_name = asset.output_files[-1]
            (figures_dir / target_name).write_bytes(asset.binary_content)
            copied = True
            written_files.append(target_name)
        if not copied and (asset.type is AssetType.IMAGE or asset.structured_content is None):
            missing_assets.append(asset.id)
        asset_records.append(
            {
                "id": asset.id,
                "page": asset.page,
                "type": asset.type.value,
                "output_files": list(asset.output_files),
                "written_files": written_files,
                "caption": list(asset.caption),
                "footnote": list(asset.footnote),
                "metadata": asset.metadata,
            }
        )
        ocr_text = asset.metadata.get("ocr_text")
        if isinstance(ocr_text, str) and ocr_text.strip():
            ocr_path = figures_dir / f"{Path(asset.output_files[-1]).stem}.ocr.json"
            ocr_path.write_text(
                json.dumps(
                    {
                        "asset_id": asset.id,
                        "page": asset.page,
                        "engine": asset.metadata.get("ocr_engine"),
                        "text": ocr_text,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            written_files.append(ocr_path.name)

    _write_jsonl(assets_path, asset_records)

    manifest = {
        "article_name": document.article_name,
        "source_export": str(document.source_export) if document.source_export else None,
        "source_pdf": str(document.source_pdf) if document.source_pdf else None,
        "counts": {
            "content_blocks": len(document.blocks),
            "figures_and_tables": len(document.assets),
            "citations": len(document.citations),
            "filtered_headers_footers": len(document.filtered_margins),
        },
        "missing_assets": missing_assets,
        **document.metadata,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "content": content_path,
        "figures": figures_dir,
        "assets": assets_path,
        "citations": citations_path,
        "manifest": manifest_path,
    }
