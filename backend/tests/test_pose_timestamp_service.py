from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services import pose_timestamp_service as ts


def frame(record_ns: int, sensor_ns: int, points: int = 100) -> ts.BagFrame:
    return ts.BagFrame(record_ns, sensor_ns, points)


def trajectory(times: list[float]) -> list[ts.TrajectoryRow]:
    return [ts.TrajectoryRow(t, (float(i), 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
            for i, t in enumerate(times)]


class AssociationTests(unittest.TestCase):
    """docs/pose-timestamp-contract.md §3-§9."""

    def test_perfect_one_to_one_match_keys_output_by_record_time(self):
        # Sensor clock and bag record clock intentionally differ by one frame;
        # only the OUTPUT key may follow the bag record time.
        sensor_times = [100.0 + 0.1 * i for i in range(50)]
        frames = [frame(record_ns=int((t + 0.1) * 1e9), sensor_ns=int(t * 1e9))
                  for t in sensor_times]
        outcome = ts.associate_to_bag_record_time(
            frames, trajectory(sensor_times),
            max_delta_sec=0.05, min_matched_ratio=0.98,
        )
        self.assertTrue(outcome.accepted, outcome.report)
        self.assertEqual(outcome.report["matched_ratio"], 1.0)
        self.assertEqual(outcome.report["duplicate_pose_reuse_count"], 0)
        self.assertEqual(outcome.report["non_monotonic_match_count"], 0)
        self.assertEqual(outcome.report["head_unmatched_count"], 0)
        # Timestamp column = bag record time, transform = matched native pose.
        self.assertEqual(outcome.rows[0][0], ts.format_record_time(int(100.1 * 1e9)))
        self.assertEqual(outcome.rows[0][1][0], 0.0)
        self.assertEqual(outcome.rows[1][1][0], 1.0)

    def test_head_gap_from_glim_initialisation_is_accepted_and_reported(self):
        sensor_times = [100.0 + 0.1 * i for i in range(1000)]
        frames = [frame(record_ns=int(t * 1e9), sensor_ns=int(t * 1e9)) for t in sensor_times]
        # GLIM starts 15 LiDAR frames later than the bag.
        native = trajectory(sensor_times[15:])
        outcome = ts.associate_to_bag_record_time(
            frames, native, max_delta_sec=0.05, min_matched_ratio=0.98,
        )
        self.assertTrue(outcome.accepted, outcome.report)
        self.assertEqual(outcome.report["head_unmatched_count"], 15)
        self.assertEqual(outcome.report["tail_unmatched_count"], 0)
        self.assertEqual(outcome.report["interior_unmatched_count"], 0)
        self.assertGreaterEqual(outcome.report["matched_ratio"], 0.98)

    def test_residual_beyond_tolerance_is_skipped_and_can_reject_handoff(self):
        sensor_times = [100.0 + 0.1 * i for i in range(100)]
        frames = [frame(record_ns=int(t * 1e9), sensor_ns=int(t * 1e9)) for t in sensor_times]
        # Native poses are far sparser than the LiDAR frames, so most frames have
        # no pose within the 0.05 s tolerance and must be skipped, not guessed.
        native = trajectory([100.0 + 0.5 * i for i in range(20)])
        outcome = ts.associate_to_bag_record_time(
            frames, native, max_delta_sec=0.05, min_matched_ratio=0.98,
        )
        self.assertFalse(outcome.accepted)
        self.assertGreater(outcome.report["matched_count"], 0)
        self.assertGreater(outcome.report["skipped_count"], 0)
        self.assertEqual(
            outcome.report["matched_count"] + outcome.report["skipped_count"], len(frames)
        )
        self.assertEqual(outcome.report["matched_ratio"], 0.2)
        self.assertTrue(outcome.report["reject_reasons"])
        self.assertEqual(outcome.rows, [])

    def test_low_matched_ratio_is_rejected_at_the_strict_default(self):
        sensor_times = [100.0 + 0.1 * i for i in range(100)]
        frames = [frame(record_ns=int(t * 1e9), sensor_ns=int(t * 1e9)) for t in sensor_times]
        native = trajectory(sensor_times[40:])  # 60/100 = 0.60 < 0.98
        outcome = ts.associate_to_bag_record_time(
            frames, native, max_delta_sec=0.05, min_matched_ratio=0.98,
        )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.report["matched_ratio"], 0.6)
        self.assertTrue(any("matched_ratio" in reason for reason in outcome.reject_reasons))

    def test_non_monotonic_association_is_a_hard_failure(self):
        # Bag record times increase, but the frames' sensor stamps jump back and
        # forth, so the matched native indices move backwards.
        sensor_sequence = [100.0, 100.1, 100.2, 100.15, 100.3, 100.25, 100.4]
        frames = [frame(record_ns=int((100.0 + 0.1 * i) * 1e9), sensor_ns=int(t * 1e9))
                  for i, t in enumerate(sensor_sequence)]
        native_times = sorted(set(sensor_sequence))
        outcome = ts.associate_to_bag_record_time(
            frames, trajectory(native_times), max_delta_sec=0.05, min_matched_ratio=0.5,
        )
        self.assertFalse(outcome.accepted)
        self.assertGreater(outcome.report["non_monotonic_match_count"], 0)
        self.assertTrue(any("non_monotonic" in reason for reason in outcome.reject_reasons))

    def test_duplicate_pose_reuse_is_reported_and_blocks_by_default(self):
        # Two frames sit closer to the same native pose than to their neighbours,
        # which is exactly the "one frame shift / rate mismatch" smell.
        sensor_sequence = [100.0, 100.02, 100.05, 100.10, 100.20, 100.30]
        frames = [frame(record_ns=int((100.0 + 0.2 * i) * 1e9), sensor_ns=int(t * 1e9))
                  for i, t in enumerate(sensor_sequence)]
        native = trajectory([100.0, 100.1, 100.2, 100.3])
        outcome = ts.associate_to_bag_record_time(
            frames, native, max_delta_sec=0.05, min_matched_ratio=0.9,
        )
        self.assertGreaterEqual(outcome.report["duplicate_pose_reuse_count"], 1)
        self.assertFalse(outcome.accepted)
        self.assertTrue(any("duplicate_pose_reuse" in reason for reason in outcome.reject_reasons))
        # An operator may accept the reuse explicitly after inspecting the report.
        relaxed = ts.associate_to_bag_record_time(
            frames, native, max_delta_sec=0.05, min_matched_ratio=0.9,
            max_duplicate_reuse_count=5,
        )
        self.assertTrue(relaxed.accepted)

    def test_invalid_thresholds_are_structural_errors(self):
        frames = [frame(1, 1)]
        with self.assertRaises(ts.PoseTimestampError):
            ts.associate_to_bag_record_time(frames, trajectory([1.0]), max_delta_sec=0.0,
                                            min_matched_ratio=0.98)
        with self.assertRaises(ts.PoseTimestampError):
            ts.associate_to_bag_record_time(frames, trajectory([1.0]), max_delta_sec=0.05,
                                            min_matched_ratio=0.0)
        with self.assertRaises(ts.PoseTimestampError):
            ts.associate_to_bag_record_time([], trajectory([1.0]), max_delta_sec=0.05,
                                            min_matched_ratio=0.98)


class ParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_pose_trajectory_validation(self):
        good = self.write("poses.txt", "1.0 0 0 0 0 0 0 1\n2.0 1 0 0 0 0 0 1\n")
        self.assertEqual(len(ts.read_pose_trajectory(good)), 2)
        for text, expected in (
            ("1.0 0 0 0 0 0 1\n", "expected 8 columns"),
            ("2.0 0 0 0 0 0 0 1\n1.0 1 0 0 0 0 0 1\n", "strictly increasing"),
            ("1.0 0 0 0 0 0 0 2\n", "quaternion"),
            ("", "empty"),
        ):
            with self.assertRaisesRegex(ts.PoseTimestampError, expected):
                ts.read_pose_trajectory(self.write("bad.txt", text))

    def test_bag_index_parsing_and_rejects_unsorted_records(self):
        path = self.write("bag_index.tsv",
                          "# record\tsensor\tpoints\n"
                          "1000000000\t900000000\t20160\n"
                          "1100000000\t1000000000\t20160\n")
        frames = ts.read_bag_frame_index(path)
        self.assertEqual(frames[0], frame(1000000000, 900000000, 20160))
        bad = self.write("bad_index.tsv", "2000\t1\n1000\t2\n")
        with self.assertRaisesRegex(ts.PoseTimestampError, "strictly increasing"):
            ts.read_bag_frame_index(bad)
        with self.assertRaisesRegex(ts.PoseTimestampError, "no LiDAR frames"):
            ts.read_bag_frame_index(self.write("empty_index.tsv", "# only a header\n"))

    def test_write_and_read_round_trip_and_report(self):
        path = self.root / "nested" / "poses.txt"
        rows = [(ts.format_record_time(1_500_000_000), (1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0))]
        self.assertEqual(ts.write_pose_trajectory(path, rows), 1)
        parsed = ts.read_pose_trajectory(path)
        self.assertAlmostEqual(parsed[0].timestamp, 1.5)
        self.assertEqual(parsed[0].values[0:3], (1.0, 2.0, 3.0))
        report_path = self.root / "association.json"
        ts.write_association_report(report_path, {"accepted": True})
        self.assertEqual(ts.read_association_report(report_path)["accepted"], True)
        self.assertIn("generated_at", ts.read_association_report(report_path))


if __name__ == "__main__":
    unittest.main()
