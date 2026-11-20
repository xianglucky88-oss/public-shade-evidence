from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from math import isfinite
from typing import Any

Row = dict[str, Any]


def read_rows(data: Row, field: str = "records") -> list[Row]:
    rows = data[field]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{field} must contain JSON objects")
    return rows


def text(row: Row, field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def number(row: Row, field: str, *, minimum: float | None = None) -> float:
    value = row[field]
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return float(value)


def integer(row: Row, field: str, *, minimum: int = 0) -> int:
    value = row[field]
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an integer of at least {minimum}")
    return value


def flag(row: Row, field: str) -> bool:
    value = row[field]
    if type(value) is not bool:
        raise ValueError(f"{field} must be true or false")
    return value


def index_rows(rows: list[Row], field: str) -> dict[str, Row]:
    result = {}
    for row in rows:
        key = text(row, field)
        if key in result:
            raise ValueError(f"duplicate {field}: {key}")
        result[key] = row
    return result


def apply_rows(data: Row, transform: Callable[[Row], Row]) -> list[Row]:
    return [
        {"fact_id": key, **transform(row)}
        for key, row in index_rows(read_rows(data), "id").items()
    ]


def read_array(row: Row, field: str) -> list[Any]:
    value = row[field]
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def choice(row: Row, field: str, allowed: set[str]) -> str:
    value = text(row, field)
    if value not in allowed:
        raise ValueError(f"unexpected {field}: {value!r}")
    return value


def day(row: Row, field: str) -> date:
    value = text(row, field)
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return result


def span(row: Row, start: str, end: str) -> tuple[int, int]:
    a = integer(row, start)
    return a, integer(row, end, minimum=a + 1)


def merge_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def clock_seconds(value: Any, field: str = "time") -> int:
    """Parse a seconds-of-day value, accepting ``HH:MM``/``HH:MM:SS`` text."""
    if type(value) is int:
        if not 0 <= value <= 86_400:
            raise ValueError(f"{field} must be between 00:00 and 24:00")
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be seconds of day or HH:MM[:SS]")
    parts = value.split(":")
    if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
        raise ValueError(f"{field} must be seconds of day or HH:MM[:SS]")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if minute > 59 or second > 59 or hour > 24 or (hour == 24 and (minute or second)):
        raise ValueError(f"{field} must be between 00:00 and 24:00")
    return hour * 3600 + minute * 60 + second


def clock_text(value: int) -> str:
    hour, rest = divmod(value, 3600)
    minute, second = divmod(rest, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


Rect = tuple[float, float, float, float]


def rectangle(row: Row, field: str) -> Rect:
    corners = read_array(row, field)
    if len(corners) != 4:
        raise ValueError(f"{field} must have four rectangle coordinates")
    x0, y0, x1, y1 = (number({field: value}, field) for value in corners)
    if x0 >= x1 or y0 >= y1:
        raise ValueError(f"{field} must have positive width and height")
    return x0, y0, x1, y1


def rectangles(row: Row, field: str) -> list[Rect]:
    """Read a single rectangle or a list of rectangles (e.g. a queue and its tail)."""
    value = read_array(row, field)
    if value and all(type(item) in (int, float) for item in value):
        return [rectangle(row, field)]
    if not value:
        raise ValueError(f"{field} must hold at least one rectangle")
    return [rectangle({field: item}, field) for item in value]


def area(rect: Rect) -> float:
    x0, y0, x1, y1 = rect
    return (x1 - x0) * (y1 - y0)


def intersection_area(a: Rect, b: Rect) -> float:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def union_area(rects: Iterable[Rect]) -> float:
    """Area covered by at least one rectangle, without double counting overlaps."""
    rects = [r for r in rects if r[2] > r[0] and r[3] > r[1]]
    columns = sorted({x for rect in rects for x in (rect[0], rect[2])})
    total = 0.0
    for left, right in zip(columns, columns[1:]):
        bands = sorted((rect[1], rect[3]) for rect in rects if rect[0] < right and rect[2] > left)
        covered = 0.0
        if bands:
            low, high = bands[0]
            for start, end in bands[1:]:
                if start > high:
                    covered += high - low
                    low, high = start, end
                else:
                    high = max(high, end)
            covered += high - low
        total += (right - left) * covered
    return total


def union_within(bounds: Iterable[Rect], rects: Iterable[Rect]) -> float:
    """Union area of ``rects`` clipped to the union of ``bounds``, counted once."""
    bounds = list(bounds)
    clipped = []
    for rect in rects:
        for bound in bounds:
            x0, y0 = max(bound[0], rect[0]), max(bound[1], rect[1])
            x1, y1 = min(bound[2], rect[2]), min(bound[3], rect[3])
            if x1 > x0 and y1 > y0:
                clipped.append((x0, y0, x1, y1))
    return union_area(clipped)
