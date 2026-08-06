"""Pluggable OCR engines used only when native and MinerU text are inadequate."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol


class OcrEngine(Protocol):
    name: str

    def recognize_page(self, image: bytes, page: int) -> str: ...


class TesseractOcrEngine:
    name = "tesseract"

    def __init__(
        self,
        *,
        executable: str = "tesseract",
        languages: str = "chi_sim+eng",
        page_segmentation_mode: int = 6,
        timeout_seconds: int = 300,
    ) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise RuntimeError(
                f"OCR executable '{executable}' was not found. Install Tesseract and the "
                f"language data '{languages}', or run without --ocr-engine tesseract."
            )
        self.executable = resolved
        self.languages = languages
        self.page_segmentation_mode = page_segmentation_mode
        self.timeout_seconds = timeout_seconds

    def recognize_page(self, image: bytes, page: int) -> str:
        with tempfile.TemporaryDirectory(prefix=f"hospital-ocr-page-{page}-") as directory:
            image_path = Path(directory) / "page.png"
            image_path.write_bytes(image)
            result = subprocess.run(
                [
                    self.executable,
                    str(image_path),
                    "stdout",
                    "-l",
                    self.languages,
                    "--psm",
                    str(self.page_segmentation_mode),
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        return result.stdout.strip()
