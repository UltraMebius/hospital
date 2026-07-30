from pathlib import Path

from hospital_eval.dataset import load_cases, write_cases
from hospital_eval.models import EvaluationCase


def test_cases_round_trip(tmp_path: Path) -> None:
    cases = [
        EvaluationCase(
            id="q1",
            question="推荐剂量？",
            expected_answer="5 mg",
            relevant_chunk_ids=frozenset({"doc:1"}),
            document_id="doc",
        )
    ]
    path = tmp_path / "cases.jsonl"
    write_cases(path, cases)
    assert load_cases(path) == cases

