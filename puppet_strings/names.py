"""Identifier normalization shared by every namespace."""

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Turn a sheet value into a Skedge identifier.

    "Mary Kate" -> "mary_kate", "Archery 1 & 2" -> "archery_1_2",
    "3rd Session" -> "_3rd_session".
    """
    ident = _NON_ALNUM.sub("_", text.strip().lower()).strip("_")
    if ident and ident[0].isdigit():
        ident = "_" + ident
    return ident


def check_unique(namespace: str, values: list[str]) -> None:
    """Raise ValueError if two sheet values normalize to the same identifier."""
    seen: dict[str, str] = {}
    for value in values:
        ident = normalize(value)
        if ident in seen and seen[ident] != value:
            raise ValueError(
                f"{namespace}: '{value}' and '{seen[ident]}' both normalize to '{ident}'"
            )
        seen[ident] = value
