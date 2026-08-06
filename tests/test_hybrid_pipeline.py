import json
from pathlib import Path

import pytest

from file.hybrid import _normalized_crop_bbox
from file.models import BlockType
from file.pdf_backend import NativeTextBlock
from file.pipeline import parse_hybrid_pdf


class FakePdfBackend:
    def __init__(self, _: Path) -> None:
        self.page_count = 2

    def __enter__(self) -> "FakePdfBackend":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def extract_text_blocks(self, page: int) -> list[NativeTextBlock]:
        if page == 1:
            return [
                NativeTextBlock(
                    page=page,
                    text="患者每日服用阿司匹林五毫克，连续治疗并观察临床反应。",
                    bbox=(10.0, 20.0, 200.0, 80.0),
                ),
                NativeTextBlock(
                    page=page,
                    text="[1]",
                    bbox=(190.0, 70.0, 200.0, 75.0),
                    reading_role="page_end_reference",
                ),
            ]
        return []

    def page_size(self, page: int) -> tuple[float, float]:
        assert page in {1, 2}
        return 600.0, 800.0

    def render_page(self, page: int, dpi: int = 300) -> bytes:
        assert page == 2
        assert dpi == 300
        return b"rendered-page"

    def render_region(
        self,
        page: int,
        bbox: tuple[float, float, float, float],
        dpi: int = 300,
    ) -> bytes:
        assert page == 1
        assert bbox == (8.0, 20.0, 76.0, 132.0)
        assert dpi == 450
        return b"cropped-figure"

    def figure_region(
        self,
        page: int,
        bbox: tuple[float, float, float, float],
        captions: tuple[str, ...] = (),
    ) -> tuple[float, float, float, float]:
        raise AssertionError("native PDF caption matching must not be used for MinerU crops")

    def extract_images(self) -> list[object]:
        raise AssertionError("PDF embedded-image matching must not be used")

    def extract_tables(self) -> list[object]:
        return []

    def close(self) -> None:
        return None


class FakeOcrEngine:
    name = "fake-ocr"

    def recognize_page(self, image: bytes, page: int) -> str:
        if image == b"rendered-page":
            assert page == 2
            return "第二页扫描中文已经通过光学字符识别完整提取并保存。"
        assert image == b"cropped-figure"
        assert page == 1
        return "图像内中文标注"


def test_normalizes_layout_bbox_and_adds_crop_padding() -> None:
    assert _normalized_crop_bbox((100, 200, 900, 800), (600, 800)) == (
        46.0,
        146.0,
        554.0,
        654.0,
    )
    assert _normalized_crop_bbox((20, 30, 120, 160), (600, 800)) == (
        6.0,
        16.0,
        134.0,
        174.0,
    )
    assert _normalized_crop_bbox(
        (20, 30, 120, 160),
        (600, 800),
        padding=4,
        coordinate_space="normalized_1000",
    ) == (8.0, 20.0, 76.0, 132.0)


def test_hybrid_parser_recovers_chinese_and_preserves_formula(tmp_path: Path) -> None:
    pdf_path = tmp_path / "article.pdf"
    pdf_path.write_bytes(b"fake-pdf")
    export_path = tmp_path / "article.jsonl"
    export_path.write_text(
        json.dumps(
            {
                "content_list_json": [
                    {"type": "text", "text": "Dose 5 mg", "page_idx": 0},
                    {
                        "type": "equation",
                        "text": "E=mc^2",
                        "text_format": "latex",
                        "page_idx": 0,
                    },
                    {
                        "type": "image",
                        "img_path": "missing.png",
                        "bbox": [20, 30, 120, 160],
                        "page_idx": 0,
                    },
                    {"type": "text", "text": "garbled", "page_idx": 1},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    outputs = parse_hybrid_pdf(
        pdf_path,
        tmp_path / "result",
        mineru_export=export_path,
        ocr_engine=FakeOcrEngine(),
        pdf_backend_factory=FakePdfBackend,
        ocr_figures=True,
    )

    content = [
        json.loads(line) for line in outputs["content"].read_text(encoding="utf-8").splitlines()
    ]
    assert any("阿司匹林" in block["text"] for block in content)
    assert any("光学字符识别" in block["text"] for block in content)
    assert any(
        block["type"] == BlockType.EQUATION.value and block["text"] == "E=mc^2" for block in content
    )
    page_one = [block for block in content if block["page"] == 1]
    assert page_one[-1]["text"] == "[1]"
    assert page_one[-1]["metadata"]["reading_role"] == "page_end_reference"
    assert (outputs["figures"] / "image_0001.png").read_bytes() == b"cropped-figure"
    assert (outputs["figures"] / "image_0001.ocr.json").is_file()
    assert not list(outputs["figures"].glob("pdf_image_*"))

    manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    assert manifest["page_sources"] == {"1": "native_pdf", "2": "ocr"}
    assert manifest["unresolved_text_pages"] == []
    assert manifest["ocr_engine"] == "fake-ocr"
    assert manifest["ocr_figures"] is True
    assert manifest["layout"]["body_columns"] == 1
    assert manifest["figure_extraction_source"] == "mineru"


def test_hybrid_parser_rejects_incomplete_mineru_image_geometry(tmp_path: Path) -> None:
    pdf_path = tmp_path / "article.pdf"
    pdf_path.write_bytes(b"fake-pdf")
    export_path = tmp_path / "article.jsonl"
    export_path.write_text(
        json.dumps(
            {"content_list_json": [{"type": "image", "img_path": "missing.png", "page_idx": 0}]}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="MinerU image blocks require bbox"):
        parse_hybrid_pdf(
            pdf_path,
            tmp_path / "result",
            mineru_export=export_path,
            pdf_backend_factory=FakePdfBackend,
        )
