from __future__ import annotations

from .contract import Row, apply_rows, flag, index_rows, integer, read_rows, text


def transform(row: Row) -> Row:
    """摄取已导出的巡查照片清单，在同观察点同观察时刻内选最后核准的复拍。"""
    slots = {}
    for photo, sample in index_rows(read_rows(row, "uploads"), "photo").items():
        key = (text(sample, "point"), text(sample, "visit"))
        slots.setdefault(key, [])
        if flag(sample, "approved"):
            slots[key].append((integer(sample, "revision"), photo))
    result = []
    for (point, visit), accepted in sorted(slots.items()):
        if len({version for version, _ in accepted}) != len(accepted):
            raise ValueError("multiple approved photos at the same revision")
        result.append(dict(point=point, visit=visit, photo=max(accepted)[1] if accepted else None))
    return {"visits": result}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
