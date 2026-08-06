import json
from pathlib import Path

from file.mineru import normalize_mineru_export
from file.pipeline import parse_mineru_export


def test_mineru_export_is_split_into_required_outputs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "images").mkdir(parents=True)
    (source / "images" / "figure.jpg").write_bytes(b"image-bytes")
    export_path = source / "article.jsonl"
    export = {
        "content_list_json": [
            {"type": "text", "text": "Medical Journal", "page_idx": 0},
            {"type": "text", "text": "正文含公式 $E=mc^2$", "page_idx": 0},
            {"type": "text", "text": "1", "page_idx": 0},
            {"type": "text", "text": "Medical Journal", "page_idx": 1},
            {
                "type": "image",
                "img_path": "images/figure.jpg",
                "image_caption": ["图 1"],
                "image_footnote": [],
                "page_idx": 1,
            },
            {
                "type": "table",
                "img_path": "",
                "table_body": "<table><tr><td>5 mg</td></tr></table>",
                "table_caption": ["表 1"],
                "table_footnote": [],
                "page_idx": 1,
            },
            {"type": "text", "text": "2", "page_idx": 1},
            {"type": "text", "text": "Medical Journal", "page_idx": 2},
            {"type": "text", "text": "参考文献", "text_level": 1, "page_idx": 2},
            {"type": "text", "text": "[1] Author. Article. 2026.", "page_idx": 2},
            {"type": "text", "text": "3", "page_idx": 2},
        ]
    }
    export_path.write_text(json.dumps(export, ensure_ascii=False) + "\n", encoding="utf-8")

    outputs = parse_mineru_export(
        export_path,
        tmp_path / "result",
        header_footer_edge_blocks=1,
    )

    content = [
        json.loads(line) for line in outputs["content"].read_text(encoding="utf-8").splitlines()
    ]
    assert all(block["text"] != "Medical Journal" for block in content)
    assert all(block["text"] not in {"1", "2", "3"} for block in content)
    assert any("$E=mc^2$" in block["text"] for block in content)
    assert (outputs["figures"] / "image_0001.jpg").read_bytes() == b"image-bytes"
    table = (outputs["figures"] / "table_0001.md").read_text(encoding="utf-8")
    assert table == "| 5 mg |\n| --- |\n"

    citations = [
        json.loads(line) for line in outputs["citations"].read_text(encoding="utf-8").splitlines()
    ]
    assert [item["raw_text"] for item in citations] == ["[1] Author. Article. 2026."]

    manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    assert manifest["counts"]["filtered_headers_footers"] == 6
    assert manifest["missing_assets"] == []


def test_mineru_middle_json_unions_image_body_caption_and_footnote(tmp_path: Path) -> None:
    export_path = tmp_path / "article.jsonl"
    export_path.write_text(
        json.dumps(
            {
                "content_list_json": [
                    {
                        "type": "image",
                        "img_path": "images/figure.png",
                        "image_caption": ["Figure 1 caption"],
                        "image_footnote": ["Note: detail"],
                        "page_idx": 0,
                    }
                ],
                "middle_json": {
                    "pdf_info": [
                        {
                            "page_idx": 0,
                            "page_size": [600, 800],
                            "images": [
                                {
                                    "bbox": [100, 120, 500, 500],
                                    "blocks": [
                                        {"type": "image_body", "bbox": [100, 120, 500, 400]},
                                        {
                                            "type": "image_caption",
                                            "bbox": [110, 410, 480, 450],
                                        },
                                        {
                                            "type": "image_footnote",
                                            "bbox": [110, 460, 480, 500],
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    document = normalize_mineru_export(export_path, filter_headers_footers=False)

    asset = document.assets[0]
    assert asset.bbox == (100.0, 120.0, 500.0, 500.0)
    assert asset.metadata["bbox_source"] == "middle_json_visual_union"
    assert asset.metadata["bbox_coordinate_space"] == "page"
    assert asset.metadata["mineru_caption_in_bbox"] is True
