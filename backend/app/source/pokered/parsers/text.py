from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .errors import ParseError


@dataclass(frozen=True)
class ParsedText:
    reference: str
    status: Literal["direct", "unsupported"]
    pages: tuple[str, ...]
    reason: str | None
    source_symbol: str


def parse_direct_text(reference: str, scripts: str, texts: str) -> ParsedText:
    pointer = re.search(
        rf"^\s*dw_const\s+([A-Za-z0-9_]+),\s*{re.escape(reference)}\s*$",
        scripts,
        re.MULTILINE,
    )
    if pointer is None:
        return ParsedText(reference, "unsupported", (), "text pointer is missing", reference)
    wrapper = pointer.group(1)
    body = _label_body(scripts, wrapper)
    if re.search(r"^\s*text_asm\s*$", body, re.MULTILINE):
        return ParsedText(
            reference,
            "unsupported",
            (),
            "conditional text_asm scripts are not implemented",
            wrapper,
        )
    far_text = re.search(r"^\s*text_far\s+([A-Za-z0-9_]+)\s*$", body, re.MULTILINE)
    if far_text is None:
        return ParsedText(reference, "unsupported", (), "direct text_far is missing", wrapper)
    source_symbol = far_text.group(1)
    pages = _parse_text_body(_label_body(texts, source_symbol))
    if not pages:
        raise ParseError(f"source text {source_symbol} contains no supported text")
    return ParsedText(reference, "direct", tuple(pages), None, source_symbol)


def parse_source_text(content: str, symbol: str) -> tuple[str, ...]:
    """Parse a named far-text body used by a focused story adapter."""

    pages = _parse_text_body(_label_body(content, symbol))
    if not pages:
        raise ParseError(f"source text {symbol} contains no supported text")
    return tuple(pages)


def _label_body(content: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}::?\s*$", content, re.MULTILINE)
    if match is None:
        raise ParseError(f"missing source label {label}")
    following = content[match.end() :]
    end = re.search(r"^[A-Za-z_][A-Za-z0-9_]*::?\s*$", following, re.MULTILINE)
    return following[: end.start()] if end else following


def _parse_text_body(content: str) -> list[str]:
    pages: list[str] = []
    lines: list[str] = []
    for directive, value in re.findall(
        r'^\s*(text|line|cont|para)\s+"((?:[^"\\]|\\.)*)"', content, re.MULTILINE
    ):
        decoded = value.replace(r"\"", '"').removesuffix("@")
        if directive == "para" and lines:
            pages.append("\n".join(lines))
            lines = []
        if directive == "text" and lines:
            lines[-1] += decoded
        else:
            lines.append(decoded)
    if lines:
        pages.append("\n".join(lines))
    return pages
