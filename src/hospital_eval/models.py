"""Core, dependency-free data models shared by pipeline components."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class DocumentKind(str, Enum):
    GUIDELINE = "guideline"
    CONSENSUS = "consensus"
    ARTICLE = "article"
    DRUG_LABEL = "drug_label"
    PHARMACOPOEIA = "pharmacopoeia"
    OTHER = "other"


class FailureType(str, Enum):
    SCAN_QUALITY = "scan_quality"
    TABLE_STRUCTURE = "table_structure"
    HEADING_HIERARCHY = "heading_hierarchy"
    TEXT_SYMBOL = "text_symbol"
    READING_ORDER = "reading_order"
    CHUNK_BOUNDARY = "chunk_boundary"
    OTHER = "other"


@dataclass(frozen=True)
class Document:
    id: str
    source: Path
    kind: DocumentKind = DocumentKind.OTHER
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    text: str
    page: int | None = None
    heading_path: tuple[str, ...] = ()
    is_table: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["heading_path"] = list(self.heading_path)
        return value


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    question: str
    expected_answer: str
    relevant_chunk_ids: frozenset[str]
    document_id: str | None = None


@dataclass(frozen=True)
class FailureRecord:
    document_id: str
    failure_type: FailureType
    severity: int
    description: str
    page: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.severity <= 5:
            raise ValueError("severity must be between 1 and 5")

