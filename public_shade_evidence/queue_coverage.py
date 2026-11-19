from __future__ import annotations

from .contract import Row, apply_rows, area, flag, index_rows, intersection_area, read_rows, rectangle


def transform(row: Row) -> Row:
    """按已同步的矩形阴影和实际候车队列范围计算荫蔽比例。"""
    queue = rectangle(row, "queue")
    result = {}
    for slot, sample in index_rows(read_rows(row, "time_samples"), "slot").items():
        covered = intersection_area(queue, rectangle(sample, "shadow"))
        result[slot] = {"covered_m2": covered, "fraction": covered / area(queue), "peak": flag(sample, "peak")}
    return {"queue_m2": area(queue), "observations": result}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
