import copy
import json
from pathlib import Path
import unittest

from public_shade_evidence import process

ROOT = Path(__file__).resolve().parent.parent


def record(**overrides):
    row = {
        "id": "construction-service-routes",
        "closure_start_day": 9,
        "closure_end_day": 13,
        "service_day": 10,
        "max_sun_exposure_min": 15,
        "min_queue_shade": 0.5,
        "temporary_shelters": [
            {
                "shelter": "T1",
                "open_day": 10,
                "close_day": 12,
                "accepted": True,
                "queue": [0, 0, 10, 4],
                "shadows": [
                    {"from": "06:00", "to": "12:00", "shadow": [0, 0, 10, 4]},
                ],
            },
        ],
        "routes": [
            {
                "route": "R1",
                "shelter": "T1",
                "segments": [
                    {
                        "segment": "s1",
                        "walk_min": 10,
                        "accessible_from": "06:00",
                        "accessible_to": "12:00",
                        "observations": [
                            {"from": "06:00", "to": "12:00", "status": "shade"},
                        ],
                    },
                ],
            },
        ],
        "departures": [
            {"slot": "08:00", "depart_at": "08:00"},
        ],
    }
    row.update(overrides)
    return {"records": [row]}


def calendar(data):
    return process("construction-service", data)[0]["peak_calendar"]


class SampleTests(unittest.TestCase):
    def test_documented_sample_matches_expected(self):
        source = json.loads((ROOT / "examples" / "construction-service-routes.json").read_text(encoding="utf-8"))
        expected = json.loads(
            (ROOT / "tests" / "expected" / "construction-service-routes.json").read_text(encoding="utf-8")
        )
        self.assertEqual(process("construction-service", source), expected)

    def test_day_level_calendar_is_untouched_by_route_data(self):
        facts = process("construction-service", record())
        self.assertEqual(facts[0]["service_gap_days"], [9, 12])
        self.assertEqual(facts[0]["closure_days"][1], {"day": 10, "available": ["T1"]})


class RouteContinuityTests(unittest.TestCase):
    def test_continuous_walk_arrives_at_still_open_shelter(self):
        slot = calendar(record())[0]
        self.assertEqual(slot["status"], "reachable")
        self.assertEqual(slot["depart_at"], "08:00:00")
        self.assertEqual(slot["routes"][0]["arrival_at"], "08:10:00")

    def test_segment_closing_before_walker_finishes_breaks_the_trip(self):
        data = record()
        data["records"][0]["routes"][0]["segments"][0]["accessible_to"] = "08:05"
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "service_gap")
        self.assertEqual(slot["reason"], "route")
        failure = slot["routes"][0]["failures"][0]
        self.assertEqual(failure["code"], "segment_closed")
        self.assertEqual(failure["leave_at"], "08:10:00")

    def test_closing_exactly_when_walker_finishes_is_still_passable(self):
        data = record()
        data["records"][0]["routes"][0]["segments"][0]["accessible_to"] = "08:10"
        self.assertEqual(calendar(data)[0]["status"], "reachable")

    def test_waiting_for_a_closed_segment_to_reopen_is_not_a_connection(self):
        data = record()
        segment = data["records"][0]["routes"][0]["segments"][0]
        segment["accessible_from"] = "08:05"
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "service_gap")
        self.assertEqual(slot["routes"][0]["failures"][0]["code"], "not_yet_open")

    def test_earlier_segment_closing_stops_later_segments_from_being_used(self):
        data = record()
        segments = data["records"][0]["routes"][0]["segments"]
        segments[0]["accessible_to"] = "08:05"
        segments.append(
            {
                "segment": "s2",
                "walk_min": 5,
                "accessible_from": "06:00",
                "accessible_to": "12:00",
                "observations": [{"from": "06:00", "to": "12:00", "status": "shade"}],
            }
        )
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "service_gap")
        self.assertEqual(slot["routes"][0]["failures"][0]["segment"], "s1")
        self.assertIsNone(slot["routes"][0]["arrival_at"])


class ExposureTests(unittest.TestCase):
    def test_sunlight_is_measured_only_over_the_actual_passage(self):
        data = record()
        segment = data["records"][0]["routes"][0]["segments"][0]
        segment["observations"] = [
            {"from": "07:00", "to": "08:20", "status": "sunlit"},
            {"from": "08:20", "to": "09:00", "status": "shade"},
        ]
        result = calendar(data)[0]["routes"][0]
        # 06:00–07:00 没被经过，不计入暴晒；08:00–08:10 全程有观测。
        self.assertEqual(result["longest_sun_min"], 10.0)
        self.assertEqual(result["status"], "pass")

    def test_gap_between_observations_is_unobserved_not_shade(self):
        data = record()
        segment = data["records"][0]["routes"][0]["segments"][0]
        segment["observations"] = [
            {"from": "07:00", "to": "08:02", "status": "shade"},
            {"from": "08:06", "to": "09:00", "status": "shade"},
        ]
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["reason"], "route")
        self.assertEqual(
            slot["routes"][0]["unverified"],
            [{"stage": "route", "code": "shade_unobserved", "segment": "s1",
              "from": "08:02:00", "to": "08:06:00"}],
        )

    def test_consecutive_sunlit_segments_count_as_one_stretch(self):
        data = record()
        route = data["records"][0]["routes"][0]
        route["segments"] = [
            {
                "segment": "s1",
                "walk_min": 6,
                "accessible_from": "06:00",
                "accessible_to": "12:00",
                "observations": [{"from": "06:00", "to": "12:00", "status": "sunlit"}],
            },
            {
                "segment": "s2",
                "walk_min": 6,
                "accessible_from": "06:00",
                "accessible_to": "12:00",
                "observations": [{"from": "06:00", "to": "12:00", "status": "sunlit"}],
            },
        ]
        data["records"][0]["max_sun_exposure_min"] = 10
        slot = calendar(data)[0]
        self.assertEqual(slot["routes"][0]["longest_sun_min"], 12.0)
        self.assertEqual(slot["status"], "service_gap")
        self.assertEqual(slot["routes"][0]["failures"][0]["code"], "exposure_exceeded")

    def test_shade_between_segments_resets_the_stretch(self):
        data = record()
        route = data["records"][0]["routes"][0]
        route["segments"] = [
            {
                "segment": "s1",
                "walk_min": 6,
                "accessible_from": "06:00",
                "accessible_to": "12:00",
                "observations": [{"from": "06:00", "to": "12:00", "status": "sunlit"}],
            },
            {
                "segment": "s2",
                "walk_min": 1,
                "accessible_from": "06:00",
                "accessible_to": "12:00",
                "observations": [{"from": "06:00", "to": "12:00", "status": "shade"}],
            },
            {
                "segment": "s3",
                "walk_min": 6,
                "accessible_from": "06:00",
                "accessible_to": "12:00",
                "observations": [{"from": "06:00", "to": "12:00", "status": "sunlit"}],
            },
        ]
        data["records"][0]["max_sun_exposure_min"] = 10
        slot = calendar(data)[0]
        self.assertEqual(slot["routes"][0]["longest_sun_min"], 6.0)
        self.assertEqual(slot["status"], "reachable")


class QueueShadeTests(unittest.TestCase):
    def test_queue_tail_outside_the_shelter_counts_toward_the_target(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["queue"] = [[0, 0, 4, 4], [4, 0, 8, 4]]
        shelter["shadows"] = [{"from": "06:00", "to": "12:00", "shadow": [-1, -1, 5, 5]}]
        result = calendar(data)[0]["routes"][0]
        # 棚下 4×4 与伸出棚外 1×4 的队尾被遮阴 → 20/32；剩下 3×4 队尾裸露。
        self.assertEqual(result["queue_shade"], 0.625)
        self.assertEqual(result["status"], "pass")

    def test_overlapping_shadows_are_not_counted_twice(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["queue"] = [0, 0, 10, 4]
        shelter["shadows"] = [
            {"from": "06:00", "to": "12:00", "shadow": [0, 0, 6, 4]},
            {"from": "06:00", "to": "12:00", "shadow": [4, 0, 10, 4]},
        ]
        result = calendar(data)[0]["routes"][0]
        # 两块影子合起来覆盖 0–10；若重复计算会得到 1.2。
        self.assertEqual(result["queue_shade"], 1.0)

    def test_shadow_sample_must_be_in_force_at_arrival(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["shadows"] = [{"from": "06:00", "to": "08:05", "shadow": [0, 0, 10, 4]}]
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["routes"][0]["queue_shade"], None)
        self.assertEqual(slot["routes"][0]["unverified"][0]["code"], "queue_shadow_unobserved")

    def test_point_samples_apply_until_the_next_reading(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["open_time"] = "06:00"
        shelter["close_time"] = "12:00"
        shelter["shadows"] = [
            {"at": "07:40", "shadow": [0, 0, 2, 4]},
            {"at": "08:10", "shadow": [0, 0, 10, 4]},
        ]
        result = calendar(data)[0]["routes"][0]
        self.assertEqual(result["queue_shade"], 1.0)
        self.assertEqual(result["status"], "pass")

    def test_arrival_after_the_shelter_closes_is_a_gap_not_just_unverified(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["open_time"] = "06:00"
        shelter["close_time"] = "08:05"
        shelter["shadows"] = [{"at": "07:40", "shadow": [0, 0, 10, 4]}]
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "service_gap")
        self.assertEqual(slot["reason"], "arrival")
        self.assertIn("shelter_closed", [item["code"] for item in slot["routes"][0]["failures"]])

    def test_queue_recorded_as_null_is_missing_not_zero_shade(self):
        data = record()
        data["records"][0]["temporary_shelters"][0]["queue"] = None
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["routes"][0]["unverified"][0]["code"], "queue_missing")
        self.assertNotIn("08:00", process("construction-service", data)[0]["service_gap_slots"])

    def test_shadow_readings_missing_altogether_is_reported(self):
        data = record()
        data["records"][0]["temporary_shelters"][0].pop("shadows")
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["routes"][0]["unverified"][0]["code"], "queue_shadow_missing")

    def test_later_sample_applies_to_a_later_departure(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["shadows"] = [
            {"from": "06:00", "to": "08:05", "shadow": [0, 0, 2, 4]},
            {"from": "08:05", "to": "12:00", "shadow": [0, 0, 10, 4]},
        ]
        self.assertEqual(calendar(data)[0]["routes"][0]["queue_shade"], 1.0)

    def test_queue_shade_below_required_is_an_arrival_failure(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["shadows"] = [{"from": "06:00", "to": "12:00", "shadow": [0, 0, 2, 4]}]
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "service_gap")
        self.assertEqual(slot["reason"], "arrival")
        failure = slot["routes"][0]["failures"][0]
        self.assertEqual(failure["code"], "queue_shade_low")
        self.assertEqual(failure["actual"], 0.2)

    def test_shelter_whose_opening_hours_end_before_arrival(self):
        data = record()
        shelter = data["records"][0]["temporary_shelters"][0]
        shelter["open_time"] = "06:00"
        shelter["close_time"] = "08:05"
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "service_gap")
        self.assertEqual(slot["reason"], "arrival")
        self.assertEqual(slot["routes"][0]["failures"][0]["code"], "shelter_closed")


class MissingEvidenceTests(unittest.TestCase):
    def test_missing_segment_record_names_the_route_part_that_cannot_be_verified(self):
        data = record()
        data["records"][0]["routes"][0]["segments"][0]["missing"] = True
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["reason"], "route")
        self.assertEqual(
            slot["routes"][0]["unverified"],
            [{"stage": "route", "code": "segment_missing", "segment": "s1"}],
        )

    def test_route_without_segments_is_unverified(self):
        data = record()
        data["records"][0]["routes"][0].pop("segments")
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["routes"][0]["unverified"][0]["code"], "segments_missing")

    def test_route_without_a_shelter_is_unverified(self):
        data = record()
        data["records"][0]["routes"][0].pop("shelter")
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["reason"], "arrival")
        self.assertEqual(slot["routes"][0]["unverified"][0]["code"], "shelter_missing")

    def test_missing_queue_is_reported_at_arrival(self):
        data = record()
        data["records"][0]["temporary_shelters"][0].pop("queue")
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(slot["reason"], "arrival")
        self.assertEqual(slot["routes"][0]["unverified"][0]["code"], "queue_missing")

    def test_complete_alternate_route_keeps_passengers_out_of_the_gap(self):
        data = record()
        first = data["records"][0]["routes"][0]
        first["segments"][0]["accessible_to"] = "08:05"
        data["records"][0]["temporary_shelters"].append(
            {
                "shelter": "T2",
                "open_day": 9,
                "close_day": 13,
                "accepted": True,
                "queue": [0, 0, 5, 5],
                "shadows": [{"from": "06:00", "to": "12:00", "shadow": [0, 0, 5, 5]}],
            }
        )
        data["records"][0]["routes"].append(
            {
                "route": "R2",
                "shelter": "T2",
                "segments": [
                    {
                        "segment": "t1",
                        "walk_min": 14,
                        "accessible_from": "06:00",
                        "accessible_to": "12:00",
                        "observations": [{"from": "06:00", "to": "12:00", "status": "shade"}],
                    }
                ],
            }
        )
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "reachable")
        self.assertEqual(slot["routes"][0]["status"], "fail")
        self.assertEqual(slot["routes"][1]["status"], "pass")

    def test_unknown_route_evidence_blocks_the_gap_but_is_flagged(self):
        data = record()
        first = data["records"][0]["routes"][0]
        first["segments"][0]["accessible_to"] = "08:05"
        data["records"][0]["routes"].append(
            {"route": "R2", "shelter": "T1", "segments": [{"segment": "t1", "missing": True}]}
        )
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertNotIn("08:00", process("construction-service", data)[0]["service_gap_slots"])


class PeakCalendarTests(unittest.TestCase):
    def test_departure_slots_are_ordered_and_changes_explain_where_it_broke(self):
        data = record()
        shelters = data["records"][0]["temporary_shelters"]
        shelters[0]["shadows"] = [
            {"from": "06:00", "to": "08:15", "shadow": [0, 0, 10, 4]},
            {"from": "08:15", "to": "12:00", "shadow": [0, 0, 1, 4]},
        ]
        data["records"][0]["departures"] = [
            {"slot": "08:20", "depart_at": "08:20"},
            {"slot": "08:00", "depart_at": "08:00"},
        ]
        facts = process("construction-service", data)[0]
        self.assertEqual([entry["slot"] for entry in facts["peak_calendar"]], ["08:00", "08:20"])
        self.assertEqual(facts["peak_calendar"][0]["status"], "reachable")
        self.assertEqual(facts["peak_calendar"][1]["status"], "service_gap")
        self.assertEqual(
            facts["changes"],
            [{"from": "08:00", "to": "08:20", "from_status": "reachable",
              "to_status": "service_gap", "from_reason": None, "to_reason": "arrival"}],
        )
        self.assertEqual(facts["service_gap_slots"], ["08:20"])

    def test_route_and_queue_failures_are_both_named(self):
        data = record()
        data["records"][0]["temporary_shelters"][0]["shadows"] = [
            {"from": "06:00", "to": "12:00", "shadow": [0, 0, 1, 4]},
        ]
        data["records"][0]["routes"][0]["segments"][0]["accessible_to"] = "08:05"
        data["records"][0]["routes"].append(
            {
                "route": "R2",
                "shelter": "T1",
                "segments": [
                    {
                        "segment": "t1",
                        "walk_min": 5,
                        "accessible_from": "06:00",
                        "accessible_to": "12:00",
                        "observations": [{"from": "06:00", "to": "12:00", "status": "shade"}],
                    }
                ],
            }
        )
        facts = process("construction-service", data)[0]
        self.assertEqual(facts["peak_calendar"][0]["reason"], "route+arrival")
        self.assertEqual(facts["peak_calendar"][0]["status"], "service_gap")
        self.assertEqual(
            [route["failures"][0]["stage"] for route in facts["peak_calendar"][0]["routes"]],
            ["route", "arrival"],
        )


class ValidationTests(unittest.TestCase):
    def assert_rejected(self, data, message):
        with self.assertRaisesRegex(ValueError, message):
            process("construction-service", data)

    def test_routes_must_reference_a_listed_shelter(self):
        data = record()
        data["records"][0]["routes"][0]["shelter"] = "T9"
        self.assert_rejected(data, "unknown shelter")

    def test_duplicate_route_names_are_rejected(self):
        data = record()
        data["records"][0]["routes"].append(copy.deepcopy(data["records"][0]["routes"][0]))
        self.assert_rejected(data, "duplicate route")

    def test_duplicate_departure_slots_are_rejected(self):
        data = record()
        data["records"][0]["departures"].append({"slot": "08:00", "depart_at": "08:30"})
        self.assert_rejected(data, "duplicate departure slot")

    def test_departures_and_routes_are_all_or_nothing(self):
        data = record()
        data["records"][0].pop("routes")
        self.assert_rejected(data, "provided together")

    def test_required_shade_fraction_must_be_in_range(self):
        data = record()
        data["records"][0]["min_queue_shade"] = 1.5
        self.assert_rejected(data, "at most 1")

    def test_negative_walk_time_is_rejected(self):
        data = record()
        data["records"][0]["routes"][0]["segments"][0]["walk_min"] = -1
        self.assert_rejected(data, "at least 0")

    def test_observation_windows_must_not_overlap(self):
        data = record()
        data["records"][0]["routes"][0]["segments"][0]["observations"] = [
            {"from": "06:00", "to": "09:00", "status": "shade"},
            {"from": "08:00", "to": "12:00", "status": "sunlit"},
        ]
        self.assert_rejected(data, "must not overlap")

    def test_bad_clock_text_is_rejected(self):
        data = record()
        data["records"][0]["departures"][0]["depart_at"] = "8:00 am"
        self.assert_rejected(data, "HH:MM")

    def test_segement_bounds_must_be_well_formed(self):
        data = record()
        data["records"][0]["routes"][0]["segments"][0]["accessible_to"] = "06:00"
        self.assert_rejected(data, "after accessible_from")

    def test_shared_segment_catalog_can_be_referenced_by_id(self):
        data = record()
        route = data["records"][0]["routes"][0]
        route["segments"] = ["s1"]
        data["records"][0]["segments"] = [
            {
                "segment": "s1",
                "walk_min": 10,
                "accessible_from": "06:00",
                "accessible_to": "12:00",
                "observations": [{"from": "06:00", "to": "12:00", "status": "shade"}],
            }
        ]
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "reachable")
        self.assertEqual(slot["routes"][0]["arrival_at"], "08:10:00")

    def test_unknown_segment_id_is_reported_as_missing_evidence(self):
        data = record()
        data["records"][0]["routes"][0]["segments"] = ["unknown"]
        data["records"][0]["segments"] = []
        slot = calendar(data)[0]
        self.assertEqual(slot["status"], "unverified")
        self.assertEqual(
            slot["routes"][0]["unverified"][0],
            {"stage": "route", "code": "segment_missing", "segment": "unknown"},
        )

    def test_segment_reopening_window_lets_a_later_departure_through(self):
        data = record()
        segment = data["records"][0]["routes"][0]["segments"][0]
        segment.pop("accessible_from")
        segment.pop("accessible_to")
        segment["accessible_windows"] = [["06:00", "07:50"], ["08:15", "12:00"]]
        data["records"][0]["departures"] = [
            {"slot": "07:45", "depart_at": "07:45"},
            {"slot": "08:20", "depart_at": "08:20"},
        ]
        facts = process("construction-service", data)[0]
        first, second = facts["peak_calendar"]
        self.assertEqual(first["routes"][0]["failures"][0]["code"], "segment_closed")
        self.assertEqual(second["status"], "reachable")

    def test_legacy_records_without_routes_keep_the_old_fact_shape(self):
        data = record()
        row = data["records"][0]
        for field in ("service_day", "max_sun_exposure_min", "min_queue_shade", "routes", "departures"):
            row.pop(field)
        fact = process("construction-service", data)[0]
        self.assertEqual(set(fact), {"fact_id", "closure_days", "service_gap_days"})


if __name__ == "__main__":
    unittest.main()
