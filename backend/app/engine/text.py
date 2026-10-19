from __future__ import annotations

import re
from collections.abc import Mapping

# In pokered's charmap, `#` is the compressed "POKé" glyph. Resolving the
# control itself, rather than enumerating words that happen to use it, keeps
# this compatible with source phrases beyond the current Pallet milestone.
STATIC_SOURCE_TOKENS = {"#": "POKé"}
DYNAMIC_TOKEN = re.compile(r"<([A-Z][A-Z0-9_]*)>")


def normalize_source_name(value: str, fallback: str) -> str:
    """Normalize configurable names to the seven-character Gen 1 text field."""

    normalized = " ".join(value.upper().split())[:7]
    return normalized or fallback


def resolve_text_pages(
    template_pages: list[str],
    variables: Mapping[str, str],
) -> list[str]:
    """Resolve source text control tokens separately from source parsing."""

    return [_resolve_page(page, variables) for page in template_pages]


def _resolve_page(page: str, variables: Mapping[str, str]) -> str:
    resolved = page
    for token, replacement in STATIC_SOURCE_TOKENS.items():
        resolved = resolved.replace(token, replacement)
    return DYNAMIC_TOKEN.sub(
        lambda match: variables.get(match.group(1), match.group(0)),
        resolved,
    )
