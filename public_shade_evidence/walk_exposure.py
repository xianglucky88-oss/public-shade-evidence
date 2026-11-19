from __future__ import annotations

from .contract import Row, apply_rows, choice, integer, read_rows


def transform(row: Row) -> Row:
    """沿已排列的步行段合并连续曝晒，未观测段不当作曝晒或遮阴。"""
    distance = 0
    start = None
    longest = None
    unknown = []
    for segment in read_rows(row, "segments"):
        status = choice(segment, "status", {"sunlit", "shade", "unobserved"})
        end = distance + integer(segment, "length_m", minimum=1)
        if status == "sunlit":
            start = distance if start is None else start
            if longest is None or end - start > longest[1] - longest[0]:
                longest = [start, end]
        else:
            start = None
            if status == "unobserved":
                unknown.append([distance, end])
        distance = end
    return {"route_m": distance, "longest_sunlit_m": longest, "unobserved_m": unknown}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
