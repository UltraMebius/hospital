import json
from pathlib import Path

import pymupdf

from file.pipeline import parse_hybrid_pdf


def test_mineru_bbox_is_the_only_authority_for_pdf_image_crop(tmp_path: Path) -> None:
    pdf_path = tmp_path / "article.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.draw_rect((50, 100, 250, 240), color=(0, 0, 0), fill=(0.85, 0.9, 1.0))
    page.insert_text((75, 175), "MINERU FIGURE", fontsize=18)
    page.insert_text((70, 260), "Figure 1 MinerU caption", fontsize=11)
    document.save(pdf_path)
    document.close()

    export_path = tmp_path / "article_content_list.json"
    export_path.write_text(
        json.dumps(
            [
                {
                    "type": "image",
                    "img_path": "images/unavailable.png",
                    "image_caption": ["Figure 1 MinerU caption"],
                    "image_footnote": [],
                    "bbox": [166.667, 250, 833.333, 625],
                    "page_idx": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    export_path.with_name("article_middle.json").write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "page_size": [300, 400],
                        "images": [
                            {
                                "blocks": [
                                    {"type": "image_body", "bbox": [50, 100, 250, 250]},
                                    {"type": "image_caption", "bbox": [50, 255, 250, 270]},
                                ]
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    outputs = parse_hybrid_pdf(
        pdf_path,
        tmp_path / "result",
        mineru_export=export_path,
    )

    image_path = outputs["figures"] / "image_0001.png"
    pixmap = pymupdf.Pixmap(str(image_path))
    assert pixmap.width >= 1250
    assert pixmap.height >= 1050
    assets = [
        json.loads(line) for line in outputs["assets"].read_text(encoding="utf-8").splitlines()
    ]
    assert assets[0]["metadata"]["source"] == "mineru_bbox_pdf_render"
    assert assets[0]["metadata"]["crop_authority"] == "mineru"
    assert assets[0]["metadata"]["bbox_source"] == "middle_json_visual_union"
    assert not list(outputs["figures"].glob("pdf_image_*"))
