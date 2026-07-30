import pytest

from hospital_eval.evaluation import (
    evaluate_rag_case,
    normalized_edit_similarity,
    recall_at_k,
    token_f1,
)


def test_edit_similarity_handles_equal_and_empty_values() -> None:
    assert normalized_edit_similarity("指南", "指南") == 1
    assert normalized_edit_similarity("", "") == 1
    assert normalized_edit_similarity("abc", "adc") == pytest.approx(2 / 3)


def test_token_f1_counts_duplicate_tokens() -> None:
    assert token_f1("dose dose daily", "dose daily") == pytest.approx(0.8)


def test_recall_at_k() -> None:
    assert recall_at_k({"a", "b"}, ["a", "x", "b"], 2) == 0.5
    assert recall_at_k(set(), [], 1) == 1


def test_combined_rag_metrics() -> None:
    metrics = evaluate_rag_case("每日 5 mg", "每日 5 mg", {"c1"}, ["c1", "c2"])
    assert metrics.exact_match == 1
    assert metrics.token_f1 == 1
    assert metrics.recall_at_k[1] == 1

