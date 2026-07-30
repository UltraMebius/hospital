"""Small CLI for validating datasets and scoring exported RAG predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hospital_eval.dataset import load_cases
from hospital_eval.evaluation import evaluate_rag_case


def validate_dataset(path: Path) -> int:
    cases = load_cases(path)
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case IDs must be unique")
    print(json.dumps({"path": str(path), "cases": len(cases), "valid": True}, ensure_ascii=False))
    return 0


def score_predictions(cases_path: Path, predictions_path: Path) -> int:
    cases = {case.id: case for case in load_cases(cases_path)}
    results = []
    with predictions_path.open(encoding="utf-8") as lines:
        for line in lines:
            prediction = json.loads(line)
            case = cases[str(prediction["id"])]
            metrics = evaluate_rag_case(
                case.expected_answer,
                str(prediction["answer"]),
                case.relevant_chunk_ids,
                list(map(str, prediction["ranked_chunk_ids"])),
            )
            results.append(metrics)
    if not results:
        raise ValueError("predictions file is empty")
    report = {
        "cases": len(results),
        "exact_match": sum(item.exact_match for item in results) / len(results),
        "token_f1": sum(item.token_f1 for item in results) / len(results),
        "recall_at_k": {
            str(k): sum(item.recall_at_k[k] for item in results) / len(results)
            for k in results[0].recall_at_k
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hospital-eval")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-dataset", help="validate evaluation JSONL")
    validate.add_argument("path", type=Path)
    score = commands.add_parser("score", help="score RAG prediction JSONL")
    score.add_argument("cases", type=Path)
    score.add_argument("predictions", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "validate-dataset":
        return validate_dataset(args.path)
    return score_predictions(args.cases, args.predictions)


if __name__ == "__main__":
    raise SystemExit(main())

