"""Convert MinerU HTML tables into portable Markdown tables."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser

_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_DETACHED_SUBSCRIPT_RE = re.compile(
    r"(?<![A-Za-z])(?P<first>[A-Z][A-Za-z]{1,4})\s+"
    r"(?P<second>[A-Z]{1,4})\s*(?P<suffix>-[A-Za-z]+)"
)
_SUBSCRIPT_TRANSLATION = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


@dataclass(frozen=True)
class _Cell:
    text: str
    colspan: int = 1
    rowspan: int = 1


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_Cell]] = []
        self._row: list[_Cell] | None = None
        self._cell_parts: list[str] | None = None
        self._colspan = 1
        self._rowspan = 1
        self._subscript_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            attributes = dict(attrs)
            self._cell_parts = []
            self._colspan = _positive_int(attributes.get("colspan"))
            self._rowspan = _positive_int(attributes.get("rowspan"))
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("\n")
        elif tag == "sub" and self._cell_parts is not None:
            self._subscript_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(
                _Cell(
                    _clean_text("".join(self._cell_parts)),
                    colspan=self._colspan,
                    rowspan=self._rowspan,
                )
            )
            self._cell_parts = None
            self._subscript_depth = 0
        elif tag == "sub" and self._subscript_depth:
            self._subscript_depth -= 1
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            if self._subscript_depth:
                data = data.translate(_SUBSCRIPT_TRANSLATION)
            self._cell_parts.append(data)


def _positive_int(value: str | None) -> int:
    try:
        return max(1, int(value or "1"))
    except ValueError:
        return 1


def _clean_text(value: str) -> str:
    # Some MinerU exports contain entities escaped twice (for example &amp;lt;).
    value = html.unescape(html.unescape(value))
    value = _restore_detached_subscripts(value)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in value.splitlines()]
    return "<br>".join(line for line in lines if line)


def _restore_detached_subscripts(value: str) -> str:
    """Reattach formula subscripts emitted by table extraction on a second line."""

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) < 2:
        return value
    subscript_line = lines[-1]
    if not re.fullmatch(r"\d+(?:\s+\d+)+", subscript_line):
        return value
    digits = re.findall(r"\d+", subscript_line)

    def replace(match: re.Match[str]) -> str:
        if len(digits) < 2:
            return match.group(0)
        first = digits.pop(0).translate(_SUBSCRIPT_TRANSLATION)
        second = digits.pop(0).translate(_SUBSCRIPT_TRANSLATION)
        return (
            f"{match.group('first')}{first}{match.group('second')}{second}{match.group('suffix')}"
        )

    main = "\n".join(lines[:-1])
    restored, count = _DETACHED_SUBSCRIPT_RE.subn(replace, main)
    return restored if count and not digits else value


def _expand_rows(rows: list[list[_Cell]]) -> list[list[str]]:
    grid: list[list[str]] = []
    active: dict[int, tuple[int, str]] = {}
    for source_row in rows:
        row: list[str] = []
        column = 0

        def fill_active(current_row: list[str] = row) -> None:
            nonlocal column
            while column in active:
                remaining, text = active[column]
                current_row.append(text)
                if remaining <= 1:
                    del active[column]
                else:
                    active[column] = (remaining - 1, text)
                column += 1

        for cell in source_row:
            fill_active()
            for offset in range(cell.colspan):
                text = cell.text if offset == 0 else ""
                row.append(text)
                if cell.rowspan > 1:
                    active[column] = (cell.rowspan - 1, text)
                column += 1
        fill_active()
        while any(active_column >= column for active_column in active):
            if column not in active:
                row.append("")
                column += 1
                continue
            fill_active()
        grid.append(row)

    while active:
        row = []
        for column in range(max(active) + 1):
            if column not in active:
                row.append("")
                continue
            remaining, text = active[column]
            row.append(text)
            if remaining <= 1:
                del active[column]
            else:
                active[column] = (remaining - 1, text)
        grid.append(row)
    return grid


def _escape_cell(value: str) -> str:
    return value.replace("|", r"\|")


def rows_to_markdown(rows: list[list[str]]) -> str:
    """Serialize an already extracted rectangular grid as Markdown."""

    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]

    def markdown_row(row: list[str]) -> str:
        return "| " + " | ".join(_escape_cell(cell) for cell in row) + " |"

    lines = [markdown_row(normalized[0]), markdown_row(["---"] * width)]
    lines.extend(markdown_row(row) for row in normalized[1:])
    return "\n".join(lines) + "\n"


def extracted_table_to_markdown(rows: list[list[str | None]]) -> str:
    """Clean the grid returned by PyMuPDF's text-based table finder."""

    cleaned = [
        [_clean_text(cell or "") for cell in row]
        for row in rows
        if any(_clean_text(cell or "") for cell in row)
    ]
    if not cleaned:
        return ""

    if len(cleaned) >= 2 and len(cleaned[0]) == len(cleaned[1]):
        combined_lengths = [
            len(first.replace(" ", "")) + len(second.replace(" ", ""))
            for first, second in zip(cleaned[0], cleaned[1], strict=True)
        ]
        if combined_lengths and max(combined_lengths) <= 6:
            cleaned[0] = [
                f"{first}{second}" for first, second in zip(cleaned[0], cleaned[1], strict=True)
            ]
            del cleaned[1]

    merged: list[list[str]] = []
    for row in cleaned:
        if merged and row[0] and not any(row[1:]) and any(merged[-1][1:]):
            merged[-1][0] = f"{merged[-1][0]}{row[0]}"
        else:
            merged.append(row)
    return rows_to_markdown(merged)


def html_table_to_markdown(table_html: str) -> str:
    """Convert the first/combined HTML table structure to Markdown."""

    parser = _TableParser()
    parser.feed(table_html)
    parser.close()
    grid = _expand_rows(parser.rows)
    if not grid:
        return _clean_text(re.sub(r"<[^>]+>", " ", table_html))
    return rows_to_markdown(grid)
