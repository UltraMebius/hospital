from pathlib import Path

import pymupdf

from file.pdf_backend import PyMuPdfBackend


def test_extract_tables_uses_caption_to_note_region(tmp_path: Path) -> None:
    pdf_path = tmp_path / "table.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((80, 80), "Table 1 Recommendations and evidence for clinical monitoring")
    page.insert_text((100, 110), "Recommendation")
    page.insert_text((410, 110), "Grade")
    page.insert_text((510, 110), "Evidence")
    page.insert_text((100, 135), "Monitor heart rhythm")
    page.insert_text((410, 135), "I")
    page.insert_text((510, 135), "B")
    page.insert_text((80, 165), "Note: AF means atrial fibrillation")
    page.insert_text((80, 220), "Body text outside the table")
    document.save(pdf_path)
    document.close()

    with PyMuPdfBackend(pdf_path) as backend:
        tables = backend.extract_tables()

    assert len(tables) == 1
    assert tables[0].bbox[1] < 80
    assert 165 < tables[0].bbox[3] < 180
    assert "Monitor heart rhythm" in tables[0].markdown
    assert "Note: AF means atrial fibrillation" in tables[0].markdown
    assert "Body text outside" not in tables[0].markdown
