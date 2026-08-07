"""JSONL persistence for reproducible evaluation datasets."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from hospital_eval.models import EvaluationCase


def load_cases(path: Path) -> list[EvaluationCase]:
    cases = []
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            raw = json.loads(line)
            cases.append(
                EvaluationCase(
                    id=str(raw["id"]),
                    question=str(raw["question"]),
                    expected_answer=str(raw["expected_answer"]),
                    relevant_chunk_ids=frozenset(map(str, raw["relevant_chunk_ids"])),
                    document_id=raw.get("document_id"),
                )
            )
    return cases


def write_cases(path: Path, cases: Iterable[EvaluationCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for case in cases:
            output.write(
                json.dumps(
                    {
                        "id": case.id,
                        "question": case.question,
                        "expected_answer": case.expected_answer,
                        "relevant_chunk_ids": sorted(case.relevant_chunk_ids),
                        "document_id": case.document_id,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

