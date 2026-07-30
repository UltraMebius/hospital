"""Contract implemented by parsing backends."""

from pathlib import Path
from typing import Protocol

from hospital_eval.models import Chunk, Document


class Parser(Protocol):
    name: str

    def parse(self, document: Document, output_dir: Path) -> list[Chunk]:
        """Parse one document into normalized chunks."""

