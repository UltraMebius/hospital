"""Data models owned by the quality-evaluation stage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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

