"""Keep untrusted CSV text from being interpreted as spreadsheet formulas."""

from collections.abc import Iterable
from typing import Any


def safe_csv_row(values: Iterable[Any]) -> list[Any]:
    result = []
    for value in values:
        if isinstance(value, str):
            significant = value.lstrip(" \t\r\n\v\f\ufeff\x00")
            if significant.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
                value = "'" + value
        result.append(value)
    return result
