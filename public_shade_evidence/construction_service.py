from __future__ import annotations

from .contract import (
    Row,
    apply_rows,
    choice,
    clock_seconds,
    clock_text,
    flag,
    index_rows,
    integer,
    number,
    read_array,
    read_rows,
    rectangle,
    rectangles,
    span,
    text,
    union_area,
    union_within,
)

OBSERVATION_STATUSES = {"sunlit", "shade", "unobserved"}

REACHABLE = "reachable"
SERVICE_GAP = "service_gap"
UNVERIFIED = "unverified"


def _stamp(seconds: float) -> str:
    return clock_text(int(round(seconds)))


def _is_missing(entry: Row) -> bool:
    return entry.get("missing") is True


def _observations(segment: Row) -> list[tuple[int, int, str]]:
    entries = []
    for sample in read_array(segment, "observations"):
        if not isinstance(sample, dict) or "from" not in sample or "to" not in sample:
            raise ValueError("observations must be objects with from and to")
        start = clock_seconds(sample["from"], "from")
        end = clock_seconds(sample["to"], "to")
        if end <= start:
            raise ValueError("observation windows must be positive")
        entries.append((start, end, choice(sample, "status", OBSERVATION_STATUSES)))
    entries.sort()
    for (_, end, _), (start, _, _) in zip(entries, entries[1:]):
        if start < end:
            raise ValueError("shade observations must not overlap")
    return entries


def _shade_pieces(entries: list[tuple[int, int, str]], start: float, end: float) -> list[tuple[float, float, str]]:
    """按乘客实际经过的时段切分沿途观测；没被观测覆盖的部分算缺测，不当作遮阴。"""
    pieces = []

    def push(low: float, high: float, status: str) -> None:
        if high <= low:
            return
        if pieces and pieces[-1][2] == status and pieces[-1][1] == low:
            pieces[-1] = (pieces[-1][0], high, status)
        else:
            pieces.append((low, high, status))

    cursor = start
    for low, high, status in entries:
        if high <= start:
            continue
        if low >= end:
            break
        low, high = max(low, start), min(high, end)
        if low > cursor:
            push(cursor, low, "unobserved")
        push(low, high, status)
        cursor = max(cursor, high)
    if cursor < end:
        push(cursor, end, "unobserved")
    return pieces


def _longest_sunlit(pieces: list[tuple[float, float, str]]) -> float:
    """连续暴晒时长：分段步行不等于分段暴晒，相邻暴晒段要连起来算。"""
    longest = current = 0.0
    for low, high, status in pieces:
        if status == "sunlit":
            current += (high - low) / 60
            longest = max(longest, current)
        else:
            current = 0.0
    return round(longest, 3)


def _route_result(
    name: str,
    shelter: str | None,
    failures: list[Row],
    unverified: list[Row],
    arrival: float | None = None,
    walk_min: float | None = None,
    longest: float | None = None,
    queue_shade: float | None = None,
) -> Row:
    """单条线路的结论：有明确走不通的因素为 fail，只有缺测为 unverified，都没有才 pass。"""
    if failures:
        status = "fail"
    elif unverified:
        status = "unverified"
    else:
        status = "pass"
    return {
        "route": name,
        "shelter": shelter,
        "status": status,
        "walk_min": walk_min,
        "arrival_at": _stamp(arrival) if arrival is not None else None,
        "longest_sun_min": longest,
        "queue_shade": queue_shade,
        "failures": failures,
        "unverified": unverified,
    }


def _access_windows(segment: Row, label: str) -> list[tuple[int, int]]:
    """路段的无障碍开放时段：可给单一起止，也可给多个时段。"""
    if "accessible_windows" in segment and segment["accessible_windows"] is not None:
        raw = read_array(segment, "accessible_windows")
        windows = []
        for item in raw:
            if isinstance(item, dict):
                if "from" not in item or "to" not in item:
                    raise ValueError(f"{label} accessible_windows must hold open spans")
                item = [item["from"], item["to"]]
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(f"{label} accessible_windows must hold [from, to] pairs")
            low = clock_seconds(item[0], "accessible_from")
            high = clock_seconds(item[1], "accessible_to")
            if high <= low:
                raise ValueError("accessible_to must be after accessible_from")
            windows.append((low, high))
        windows.sort()
        for (_, first), (second, _) in zip(windows, windows[1:]):
            if second < first:
                raise ValueError("accessible_windows must not overlap")
        return windows
    low = clock_seconds(segment["accessible_from"], "accessible_from")
    high = clock_seconds(segment["accessible_to"], "accessible_to")
    if high <= low:
        raise ValueError("accessible_to must be after accessible_from")
    return [(low, high)]


def _walk_route(
    route: Row,
    depart: float,
    catalog: dict[str, Row],
) -> tuple[list[Row], list[Row], list[tuple[float, float, str]], tuple[float, float] | None]:
    """按给定走行时间连续走完线路；任一路段走不通就当场终止，不把等路重开算成接续。"""
    failures: list[Row] = []
    unverified: list[Row] = []
    pieces: list[tuple[float, float, str]] = []

    def stop() -> tuple[list[Row], list[Row], list[tuple[float, float, str]], None]:
        return failures, unverified, pieces, None

    segments = route.get("segments")
    if not isinstance(segments, list) or not segments:
        unverified.append({"stage": "route", "code": "segments_missing"})
        return stop()

    now = depart
    labels = set()
    for index, entry in enumerate(segments):
        if isinstance(entry, str):
            if entry not in catalog:
                unverified.append({"stage": "route", "code": "segment_missing", "segment": entry})
                return stop()
            segment = catalog[entry]
        elif isinstance(entry, dict):
            segment = entry
        else:
            raise ValueError("route segments must be segment ids or JSON objects")
        label = segment.get("segment")
        if not isinstance(label, str) or not label.strip():
            label = entry if isinstance(entry, str) else f"segments[{index}]"
        if label in labels:
            raise ValueError(f"duplicate segment: {label}")
        labels.add(label)
        if _is_missing(segment):
            unverified.append({"stage": "route", "code": "segment_missing", "segment": label})
            return stop()
        if "walk_min" not in segment:
            unverified.append({"stage": "route", "code": "segment_incomplete", "segment": label})
            return stop()
        if "accessible_windows" not in segment and not {"accessible_from", "accessible_to"} <= set(segment):
            unverified.append({"stage": "route", "code": "segment_incomplete", "segment": label})
            return stop()
        walk = number(segment, "walk_min", minimum=0)
        windows = _access_windows(segment, label)
        leave = now + walk * 60
        current = [window for window in windows if window[0] <= now < window[1]]
        if not current:
            later = [window for window in windows if window[0] > now]
            if later:
                # 只能等路段重开才走得通，按接续失败处理。
                failures.append(
                    {"stage": "route", "code": "not_yet_open", "segment": label,
                     "opens_at": _stamp(later[0][0]), "entry_at": _stamp(now)}
                )
            else:
                failures.append(
                    {"stage": "route", "code": "segment_closed", "segment": label,
                     "closes_at": _stamp(windows[-1][1]), "entry_at": _stamp(now)}
                )
            return stop()
        closes = current[0][1]
        if leave > closes:
            # 人还没走完路段就封闭。
            failures.append(
                {"stage": "route", "code": "segment_closed", "segment": label,
                 "closes_at": _stamp(closes), "leave_at": _stamp(leave)}
            )
            return stop()
        observations = segment.get("observations")
        entries = _observations(segment) if isinstance(observations, list) else []
        if observations is not None and not isinstance(observations, list):
            raise ValueError("observations must be an array")
        for low, high, status in _shade_pieces(entries, now, leave):
            if status == "unobserved":
                unverified.append(
                    {"stage": "route", "code": "shade_unobserved", "segment": label,
                     "from": _stamp(low), "to": _stamp(high)}
                )
            pieces.append((low, high, status))
        now = leave
    return failures, unverified, pieces, (depart, now)


def _shadow_windows(shelter: Row) -> list[tuple[float, float, tuple[float, float, float, float]]] | None:
    """读出分时实测阴影：起止时段，或用抽样时刻顺延到下一次抽样。"""
    samples = shelter.get("shadows")
    if samples is None:
        return None
    if not isinstance(samples, list):
        raise ValueError("shadows must be an array")
    if not samples:
        return []
    timed = [sample for sample in samples if isinstance(sample, dict) and ("from" in sample or "to" in sample)]
    if timed and len(timed) != len(samples):
        raise ValueError("shadows must not mix window samples and point samples")
    if timed:
        windows = []
        for sample in samples:
            if not isinstance(sample, dict):
                raise ValueError("shadows must contain JSON objects")
            low = clock_seconds(sample["from"], "from")
            high = clock_seconds(sample["to"], "to")
            if high <= low:
                raise ValueError("shadow sample windows must be positive")
            windows.append((low, high, rectangle(sample, "shadow")))
        return windows

    points = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("shadows must contain JSON objects")
        if "at" in sample:
            at = sample["at"]
        elif "slot" in sample:
            at = sample["slot"]
        else:
            raise ValueError("shadow samples need from/to, at or slot")
        points.append((clock_seconds(at, "at"), rectangle(sample, "shadow")))
    points.sort(key=lambda point: point[0])
    for (first, _), (second, _) in zip(points, points[1:]):
        if first == second:
            raise ValueError("duplicate shadow sample time")
    if "close_time" in shelter:
        limit = clock_seconds(shelter["close_time"], "close_time")
    else:
        limit = max(86_400, points[-1][0])
    windows = []
    for position, (start, shadow) in enumerate(points):
        end = points[position + 1][0] if position + 1 < len(points) else limit
        if end < start:
            raise ValueError(f"shadow sample at {_stamp(start)} falls after the shelter closes")
        windows.append((start, end, shadow))
    return windows


def _arrive(
    shelter_name: str,
    shelter: Row,
    service_day: int | None,
    arrival: float,
    required_shade: float,
) -> tuple[list[Row], list[Row], float | None]:
    failures: list[Row] = []
    unverified: list[Row] = []
    accepted = flag(shelter, "accepted")
    # 没写服务日就不去猜按天开放窗口落在哪一天，按天是否开放仍列在 closure_days 里。
    day_open = True
    if service_day is not None:
        open_day, close_day = span(shelter, "open_day", "close_day")
        day_open = open_day <= service_day < close_day
    if not accepted or not day_open:
        failures.append(
            {"stage": "arrival", "code": "shelter_unavailable",
             "shelter": shelter_name, "service_day": service_day}
        )
    elif "open_time" in shelter or "close_time" in shelter:
        if "open_time" not in shelter or "close_time" not in shelter:
            raise ValueError("open_time and close_time must be provided together")
        opens = clock_seconds(shelter["open_time"], "open_time")
        closes = clock_seconds(shelter["close_time"], "close_time")
        if closes <= opens:
            raise ValueError("close_time must be after open_time")
        if not (opens <= arrival < closes):
            failures.append(
                {"stage": "arrival", "code": "shelter_closed", "shelter": shelter_name,
                 "open_time": _stamp(opens), "close_time": _stamp(closes),
                 "arrival_at": _stamp(arrival)}
            )

    if not shelter.get("queue"):
        unverified.append({"stage": "arrival", "code": "queue_missing", "shelter": shelter_name})
        return failures, unverified, None
    # 队列可以是棚下矩形加伸出棚外的队尾；多块按并集计面积，重叠处不重复计入。
    queue = rectangles(shelter, "queue")
    queue_m2 = union_area(queue)
    windows = _shadow_windows(shelter)
    if windows is None:
        unverified.append({"stage": "arrival", "code": "queue_shadow_missing", "shelter": shelter_name})
        return failures, unverified, None
    active = [shadow for low, high, shadow in windows if low <= arrival < high]
    if not active:
        unverified.append(
            {"stage": "arrival", "code": "queue_shadow_unobserved",
             "shelter": shelter_name, "arrival_at": _stamp(arrival)}
        )
        return failures, unverified, None
    # 影子重叠处只算一块；队尾伸到棚外仍按队列范围计入分子和分母。
    shade = round(union_within(queue, active) / queue_m2, 6)
    if shade < required_shade:
        failures.append(
            {"stage": "arrival", "code": "queue_shade_low", "shelter": shelter_name,
             "required": required_shade, "actual": shade, "arrival_at": _stamp(arrival)}
        )
    return failures, unverified, shade


def _evaluate_route(
    route: Row,
    shelters: dict[str, Row],
    catalog: dict[str, Row],
    service_day: int | None,
    depart: float,
    exposure_limit: float,
    required_shade: float,
) -> Row:
    name = text(route, "route")
    if _is_missing(route):
        return _route_result(name, None, [], [{"stage": "route", "code": "route_missing"}])
    shelter_name = route.get("shelter")
    if not isinstance(shelter_name, str) or not shelter_name.strip():
        # 不知道终点棚就无法核实这条线路。
        return _route_result(name, None, [], [{"stage": "arrival", "code": "shelter_missing"}])
    if shelter_name not in shelters:
        raise ValueError(f"route {name} references unknown shelter {shelter_name}")
    failures, unverified, pieces, passage = _walk_route(route, depart, catalog)
    longest = _longest_sunlit(pieces)
    if passage is None:
        return _route_result(name, shelter_name, failures, unverified)
    walk_total = round((passage[1] - passage[0]) / 60, 3)
    if longest > exposure_limit:
        failures.append(
            {"stage": "route", "code": "exposure_exceeded",
             "limit_min": exposure_limit, "longest_sun_min": longest}
        )
    shelter = shelters[shelter_name]
    threshold = number(shelter, "min_queue_shade", minimum=0) if "min_queue_shade" in shelter else required_shade
    if threshold > 1:
        raise ValueError("min_queue_shade must be at most 1")
    arrival_failures, arrival_unverified, shade = _arrive(
        shelter_name, shelter, service_day, passage[1], threshold
    )
    failures.extend(arrival_failures)
    unverified.extend(arrival_unverified)
    return _route_result(
        name, shelter_name, failures, unverified,
        arrival=passage[1], walk_min=walk_total, longest=longest, queue_shade=shade,
    )


def _stages(entries) -> str | None:
    found = {entry["stage"] for entry in entries}
    ordered = [stage for stage in ("route", "arrival") if stage in found]
    return "+".join(ordered) if ordered else None


def _evaluate_departure(
    slot: str,
    depart: float,
    routes: list[Row],
    shelters: dict[str, Row],
    catalog: dict[str, Row],
    service_day: int | None,
    exposure_limit: float,
    required_shade: float,
) -> Row:
    """一个出发时段的结论；只要有线路证据完整且各项达标，就不记服务缺口。"""
    results = [
        _evaluate_route(route, shelters, catalog, service_day, depart, exposure_limit, required_shade)
        for route in routes
    ]
    statuses = [result["status"] for result in results]
    if "pass" in statuses:
        status, reason = REACHABLE, None
    elif not results:
        status, reason = UNVERIFIED, "route"
    elif all(value == "fail" for value in statuses):
        status = SERVICE_GAP
        reason = _stages(failure for result in results for failure in result["failures"]) or "route"
    else:
        # 仍有线路没核实完，不能据此把这批乘客记进服务缺口。
        status = UNVERIFIED
        reason = _stages(
            entry for result in results if result["status"] == "unverified" for entry in result["unverified"]
        ) or "route"
    return {
        "slot": slot,
        "depart_at": _stamp(depart),
        "status": status,
        "reason": reason,
        "routes": results,
    }


def _departures(row: Row) -> list[tuple[str, int]]:
    departures = []
    seen = set()
    for item in read_array(row, "departures"):
        if isinstance(item, str):
            item = {"slot": item}
        if not isinstance(item, dict):
            raise ValueError("departures must contain JSON objects or slot text")
        slot = text(item, "slot")
        if slot in seen:
            raise ValueError(f"duplicate departure slot: {slot}")
        seen.add(slot)
        # 出发时刻缺省时，槽位本身通常就是时刻。
        departures.append((slot, clock_seconds(item["depart_at"] if "depart_at" in item else slot, "depart_at")))
    departures.sort(key=lambda entry: (entry[1], entry[0]))
    return departures


def _segment_catalog(row: Row) -> dict[str, Row]:
    """共享路段目录：巡查常把路段单独列出，候选线路按 id 引用。"""
    if row.get("segments") is None:
        return {}
    catalog = {}
    for segment in read_rows(row, "segments"):
        key = segment.get("segment") if "segment" in segment else segment.get("id")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("segment must be nonempty text")
        if key in catalog:
            raise ValueError(f"duplicate segment: {key}")
        catalog[key] = segment
    return catalog


def _peak_calendar(row: Row, shelters: dict[str, Row]) -> Row | None:
    """按出发时段核对连续步行、连续暴晒与到站队列遮阴；输入未包含行程资料时跳过。"""
    if "departures" not in row and "routes" not in row:
        return None
    if "departures" not in row or "routes" not in row:
        raise ValueError("departures and routes must be provided together")
    for field in ("max_sun_exposure_min", "min_queue_shade"):
        if field not in row:
            raise ValueError(f"{field} is required with routes")
    exposure_limit = number(row, "max_sun_exposure_min", minimum=0)
    required_shade = number(row, "min_queue_shade", minimum=0)
    if required_shade > 1:
        raise ValueError("min_queue_shade must be at most 1")
    service_day = integer(row, "service_day") if "service_day" in row else None
    routes = read_rows(row, "routes")
    names = set()
    for route in routes:
        name = text(route, "route")
        if name in names:
            raise ValueError(f"duplicate route: {name}")
        names.add(name)
        if _is_missing(route):
            continue
        if "shelter" not in route:
            continue
        shelter = text(route, "shelter")
        if shelter not in shelters:
            raise ValueError(f"route {name} references unknown shelter {shelter}")

    catalog = _segment_catalog(row)
    calendar = [
        _evaluate_departure(
            slot, depart, routes, shelters, catalog, service_day, exposure_limit, required_shade
        )
        for slot, depart in _departures(row)
    ]
    changes = []
    for previous, current in zip(calendar, calendar[1:]):
        # 只记录结论不同的相邻时段；两端原因说明差异出现在路上还是到站后。
        if previous["status"] != current["status"]:
            changes.append(
                {"from": previous["slot"], "to": current["slot"],
                 "from_status": previous["status"], "to_status": current["status"],
                 "from_reason": previous["reason"], "to_reason": current["reason"]}
            )
    return {
        "service_day": service_day,
        "peak_calendar": calendar,
        "service_gap_slots": [entry["slot"] for entry in calendar if entry["status"] == SERVICE_GAP],
        "unverified_slots": [entry["slot"] for entry in calendar if entry["status"] == UNVERIFIED],
        "changes": changes,
    }


def transform(row: Row) -> Row:
    """按施工日历核对停用后的服务点是否有验收开放的临时遮棚，并按出发时段核对接续。"""
    down, resume = span(row, "closure_start_day", "closure_end_day")
    shelters = index_rows(read_rows(row, "temporary_shelters"), "shelter")
    windows = {name: (*span(record, "open_day", "close_day"), flag(record, "accepted"))
               for name, record in shelters.items()}
    availability = []
    for date in range(down, resume):
        availability.append({"day": date, "available": sorted(name for name, (start, end, accepted) in windows.items() if accepted and start <= date < end)})
    result = {"closure_days": availability, "service_gap_days": [x["day"] for x in availability if not x["available"]]}
    calendar = _peak_calendar(row, shelters)
    if calendar is not None:
        result.update(calendar)
    return result


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
