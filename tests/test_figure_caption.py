from pathlib import Path

import pymupdf

from file.pdf_backend import PyMuPdfBackend


def test_figure_region_includes_nearby_figure_caption(tmp_path: Path) -> None:
    pdf_path = tmp_path / "caption.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((90, 325), "Figure 1 Clinical workflow")
    page.insert_text((90, 600), "Figure 99 Unrelated distant text")
    document.save(pdf_path)
    document.close()

    with PyMuPdfBackend(pdf_path) as backend:
        region = backend.figure_region(1, (80.0, 100.0, 500.0, 300.0))

    assert region[0:3] == (80.0, 100.0, 500.0)
    assert 325.0 < region[3] < 350.0
