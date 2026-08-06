"""Quality signals used to route each PDF page to native text, MinerU, or OCR."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CJK_RE = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SUSPICIOUS = frozenset({"�", "□", "■", "\x00"})


@dataclass(frozen=True)
class TextQuality:
    visible_characters: int
    cjk_characters: int
    suspicious_characters: int
    suspicious_ratio: float
    score: float
    acceptable: bool

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "visible_characters": self.visible_characters,
            "cjk_characters": self.cjk_characters,
            "suspicious_characters": self.suspicious_characters,
            "suspicious_ratio": self.suspicious_ratio,
            "score": self.score,
            "acceptable": self.acceptable,
        }


def assess_text_quality(
    text: str,
    *,
    minimum_visible_characters: int = 20,
    minimum_cjk_characters: int = 4,
    maximum_suspicious_ratio: float = 0.05,
) -> TextQuality:
    visible = [character for character in text if not character.isspace()]
    cjk_count = len(_CJK_RE.findall(text))
    suspicious_count = sum(character in _SUSPICIOUS for character in visible)
    suspicious_ratio = suspicious_count / len(visible) if visible else 1.0
    acceptable = (
        len(visible) >= minimum_visible_characters
        and cjk_count >= minimum_cjk_characters
        and suspicious_ratio <= maximum_suspicious_ratio
    )
    score = len(visible) + 3 * cjk_count - 10 * suspicious_count
    return TextQuality(
        visible_characters=len(visible),
        cjk_characters=cjk_count,
        suspicious_characters=suspicious_count,
        suspicious_ratio=suspicious_ratio,
        score=float(score),
        acceptable=acceptable,
    )
