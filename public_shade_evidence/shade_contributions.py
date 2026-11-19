from __future__ import annotations

from .contract import Row, apply_rows, flag, intersection_area, read_rows, rectangle


def transform(row: Row) -> Row:
    """按已划分的不相交矩形观察单元汇总树、建筑和共用遮阴。"""
    public = rectangle(row, "public_area")
    totals = {"tree": 0, "building": 0, "shared": 0, "unattributed": 0}
    used = []
    for cell in read_rows(row, "shade_cells"):
        bounds = rectangle(cell, "bounds")
        if any(intersection_area(bounds, prev) > 0 for prev in used):
            raise ValueError("shade cells must not overlap")
        used.append(bounds)
        sources = (flag(cell, "tree"), flag(cell, "building"))
        label = {(True, True): "shared", (True, False): "tree", (False, True): "building", (False, False): "unattributed"}[sources]
        totals[label] += intersection_area(public, bounds)
    return {"public_shade_m2": totals}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
