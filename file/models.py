"""Data contracts owned by the document parsing stage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class BlockType(str, Enum):
    TEXT = "text"
    TITLE = "title"
    EQUATION = "equation"
    IMAGE = "image"
    TABLE = "table"


class AssetType(str, Enum):
    IMAGE = "image"
    TABLE = "table"


@dataclass(frozen=True)
class ContentBlock:
    id: str
    page: int
    order: int
    type: BlockType
    text: str = ""
    level: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    asset_paths: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["type"] = self.type.value
        value["asset_paths"] = list(self.asset_paths)
        return value


@dataclass(frozen=True)
class ExtractedAsset:
    id: str
    page: int
    type: AssetType
    output_files: tuple[str, ...]
    source_path: Path | None = None
    binary_content: bytes | None = None
    bbox: tuple[float, float, float, float] | None = None
    structured_content: str | None = None
    caption: tuple[str, ...] = ()
    footnote: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    id: str
    page: int
    order: int
    raw_text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParsedDocument:
    article_name: str
    source_export: Path | None
    source_pdf: Path | None
    blocks: tuple[ContentBlock, ...]
    assets: tuple[ExtractedAsset, ...]
    citations: tuple[Citation, ...]
    filtered_margins: tuple[ContentBlock, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
