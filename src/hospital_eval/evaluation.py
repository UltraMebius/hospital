"""Metrics for the parsing layer and downstream RAG layer."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w]+|[^\w\s]", text.casefold(), flags=re.UNICODE)


def normalized_edit_similarity(reference: str, prediction: str) -> float:
    """Return character similarity in [0, 1] using Levenshtein distance."""
    if not reference and not prediction:
        return 1.0
    previous = list(range(len(prediction) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(prediction, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return 1 - previous[-1] / max(len(reference), len(prediction))


def exact_match(reference: str, prediction: str) -> float:
    def normalize(value: str) -> str:
        return " ".join(_tokens(value))

    return float(normalize(reference) == normalize(prediction))


def token_f1(reference: str, prediction: str) -> float:
    reference_tokens = _tokens(reference)
    prediction_tokens = _tokens(prediction)
    if not reference_tokens or not prediction_tokens:
        return float(reference_tokens == prediction_tokens)
    remaining = list(reference_tokens)
    matches = 0
    for token in prediction_tokens:
        if token in remaining:
            remaining.remove(token)
            matches += 1
    precision = matches / len(prediction_tokens)
    recall = matches / len(reference_tokens)
    return 2 * precision * recall / (precision + recall) if matches else 0.0


def recall_at_k(relevant_ids: Iterable[str], ranked_ids: Sequence[str], k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 1.0
    return len(relevant.intersection(ranked_ids[:k])) / len(relevant)


@dataclass(frozen=True)
class RagMetrics:
    exact_match: float
    token_f1: float
    recall_at_k: dict[int, float]


def evaluate_rag_case(
    expected_answer: str,
    predicted_answer: str,
    relevant_ids: Iterable[str],
    ranked_ids: Sequence[str],
    cutoffs: Sequence[int] = (1, 3, 5, 10),
) -> RagMetrics:
    return RagMetrics(
        exact_match=exact_match(expected_answer, predicted_answer),
        token_f1=token_f1(expected_answer, predicted_answer),
        recall_at_k={k: recall_at_k(relevant_ids, ranked_ids, k) for k in cutoffs},
    )
