"""Configurable command-line adapter for MinerU.

The adapter deliberately does not pin MinerU as a Python dependency: GPU and model
environments can provide their own installation while experiments keep the exact
command in version-controlled configuration.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hospital_eval.models import Chunk, Document


class MinerUCommandParser:
    def __init__(
        self,
        command: list[str],
        backend: str = "vlm",
        timeout_seconds: int = 1800,
    ) -> None:
        if not command:
            raise ValueError("command cannot be empty")
        self.command = command
        self.backend = backend
        self.timeout_seconds = timeout_seconds
        self.name = f"mineru-{backend}"

    def parse(self, document: Document, output_dir: Path) -> list[Chunk]:
        document_output = output_dir / document.id
        document_output.mkdir(parents=True, exist_ok=True)
        values = {
            "input": str(document.source),
            "output": str(document_output),
            "backend": self.backend,
        }
        command = [part.format_map(values) for part in self.command]
        subprocess.run(command, check=True, timeout=self.timeout_seconds)
        return self._load_chunks(document, document_output)

    @staticmethod
    def _load_chunks(document: Document, output_dir: Path) -> list[Chunk]:
        normalized = output_dir / "chunks.jsonl"
        if not normalized.exists():
            raise FileNotFoundError(
                f"Parser did not create {normalized}. Add a normalization step that writes "
                "one JSON object per line with at least a 'text' field."
            )

        chunks: list[Chunk] = []
        with normalized.open(encoding="utf-8") as lines:
            for index, line in enumerate(lines):
                raw = json.loads(line)
                chunks.append(
                    Chunk(
                        id=str(raw.get("id", f"{document.id}:{index}")),
                        document_id=document.id,
                        text=str(raw["text"]),
                        page=raw.get("page"),
                        heading_path=tuple(raw.get("heading_path", [])),
                        is_table=bool(raw.get("is_table", False)),
                        metadata=raw.get("metadata", {}),
                    )
                )
        return chunks

