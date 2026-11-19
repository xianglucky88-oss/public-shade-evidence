from __future__ import annotations

from .contract import Row, apply_rows, flag, index_rows, read_rows, span


def transform(row: Row) -> Row:
    """按施工日历核对停用后的服务点是否有验收开放的临时遮棚。"""
    down, resume = span(row, "closure_start_day", "closure_end_day")
    windows = {name: (*span(record, "open_day", "close_day"), flag(record, "accepted"))
               for name, record in index_rows(read_rows(row, "temporary_shelters"), "shelter").items()}
    availability = []
    for date in range(down, resume):
        availability.append({"day": date, "available": sorted(name for name, (start, end, accepted) in windows.items() if accepted and start <= date < end)})
    return {"closure_days": availability, "service_gap_days": [x["day"] for x in availability if not x["available"]]}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
