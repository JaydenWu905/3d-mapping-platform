"""Explicit timestamp association between a Pose backend and Surface.

Two timestamp conventions exist in this platform and they are *not* the same
clock (docs/pose-timestamp-contract.md):

* **native Pose clock** — the physical LiDAR sensor/header timestamp.  GLIM's
  ``traj_lidar.txt`` is keyed by it (``T_world_lidar`` at the LiDAR frame time).
* **Surface lookup key** — the ROS1 bag *record* timestamp of each LiDAR
  message.  MrHash-LiDAR (``Ros1Reader``) iterates the bag and looks a pose up
  by the bag time it read, exactly as the registered Oxford dataset declares in
  ``input_manifest.timebase.lookup_key``.

The two differ by the recorder latency (about one LiDAR frame on the INS bag),
so matching the files by their timestamp column alone would silently attach the
wrong pose to every frame.

This module performs the conversion explicitly:

1. the ROS1 bridge writes ``bag_index.tsv`` while streaming
   (``record_timestamp_ns  sensor_timestamp_ns  point_count`` per LiDAR frame);
2. for every bag frame the nearest native Pose sample is selected *in the
   native sensor clock*, using that frame's own sensor timestamp;
3. the emitted trajectory is keyed by the bag record timestamp — exact by
   construction — and the residual of step 2 is measured, bounded by
   ``max_delta_sec`` and reported in ``association.json``.

The association never interpolates and never alters the matched transform.  A
result that does not satisfy the configured quality gates is *rejected*
(``accepted=false`` plus explicit reasons) instead of being quietly emitted.
"""
from __future__ import annotations

import bisect
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services.pose_spec import (
    BAG_RECORD_CLOCK,
    BAG_RECORD_LOOKUP_KEY,
    NATIVE_SENSOR_CLOCK,
    NATIVE_SENSOR_LOOKUP_KEY,
    POSE_SEMANTICS,
    QUATERNION_ORDER,
    TRANSLATION_UNIT,
)

__all__ = [
    "POSE_SEMANTICS",
    "TRANSLATION_UNIT",
    "QUATERNION_ORDER",
    "NATIVE_SENSOR_LOOKUP_KEY",
    "BAG_RECORD_LOOKUP_KEY",
    "NATIVE_SENSOR_CLOCK",
    "BAG_RECORD_CLOCK",
    "ASSOCIATION_METHOD",
    "PoseTimestampError",
    "TrajectoryRow",
    "BagFrame",
    "AssociationOutcome",
    "read_pose_trajectory",
    "read_bag_frame_index",
    "associate_to_bag_record_time",
    "write_pose_trajectory",
    "format_record_time",
    "write_association_report",
]


class PoseTimestampError(ValueError):
    """Structural problem that makes association impossible (not a quality gate)."""


#: Reported verbatim in association.json so the method is auditable.
ASSOCIATION_METHOD = "nearest_native_pose_by_sensor_timestamp"


@dataclass(frozen=True)
class TrajectoryRow:
    timestamp: float
    values: tuple[float, ...]  # 7 numbers: tx ty tz qx qy qz qw


@dataclass(frozen=True)
class BagFrame:
    record_time_ns: int
    sensor_time_ns: int
    point_count: int = 0


def read_pose_trajectory(path: Path, *, expected_columns: int = 8) -> list[TrajectoryRow]:
    """Parse ``timestamp tx ty tz qx qy qz qw`` with the platform's strict rules."""
    rows: list[TrajectoryRow] = []
    previous = -math.inf
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            fields = raw.split()
            if len(fields) != expected_columns:
                raise PoseTimestampError(
                    f"{path.name} line {line_no}: expected {expected_columns} columns, "
                    f"got {len(fields)}"
                )
            try:
                values = [float(value) for value in fields]
            except ValueError as exc:
                raise PoseTimestampError(f"{path.name} line {line_no}: non-numeric value") from exc
            if not all(math.isfinite(value) for value in values):
                raise PoseTimestampError(f"{path.name} line {line_no}: non-finite value")
            if values[0] <= previous:
                raise PoseTimestampError(
                    f"{path.name} line {line_no}: timestamps are not strictly increasing"
                )
            norm = math.sqrt(sum(value * value for value in values[4:8]))
            if not 0.98 <= norm <= 1.02:
                raise PoseTimestampError(
                    f"{path.name} line {line_no}: quaternion norm {norm:.6f} is invalid"
                )
            previous = values[0]
            rows.append(TrajectoryRow(values[0], tuple(values[1:8])))
    if not rows:
        raise PoseTimestampError(f"{path.name} is empty")
    return rows


def read_bag_frame_index(path: Path) -> list[BagFrame]:
    """Read ``bag_index.tsv``: ``record_timestamp_ns  sensor_timestamp_ns  [point_count]``."""
    frames: list[BagFrame] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            fields = raw.split()
            if len(fields) < 2:
                raise PoseTimestampError(
                    f"{path.name} line {line_no}: expected at least 2 columns "
                    "(record_timestamp_ns sensor_timestamp_ns)"
                )
            try:
                record_time = int(fields[0])
                sensor_time = int(fields[1])
                points = int(fields[2]) if len(fields) > 2 else 0
            except ValueError as exc:
                raise PoseTimestampError(
                    f"{path.name} line {line_no}: non-integer timestamp"
                ) from exc
            frames.append(BagFrame(record_time, sensor_time, points))
    if not frames:
        raise PoseTimestampError(f"{path.name} contains no LiDAR frames")
    record_times = [frame.record_time_ns for frame in frames]
    if any(b <= a for a, b in zip(record_times, record_times[1:])):
        raise PoseTimestampError(f"{path.name}: bag record timestamps are not strictly increasing")
    return frames


@dataclass
class AssociationOutcome:
    """Result of one association attempt (never raises on quality gates)."""

    accepted: bool
    rows: list[tuple[str, tuple[float, ...]]]
    report: dict[str, Any]

    @property
    def reject_reasons(self) -> list[str]:
        return list(self.report.get("reject_reasons") or [])


def associate_to_bag_record_time(
    frames: Iterable[BagFrame],
    trajectory: list[TrajectoryRow],
    *,
    max_delta_sec: float,
    min_matched_ratio: float,
    max_duplicate_reuse_count: int = 0,
    native_lookup_key: str = NATIVE_SENSOR_LOOKUP_KEY,
    output_lookup_key: str = BAG_RECORD_LOOKUP_KEY,
) -> AssociationOutcome:
    """Key ``trajectory`` by bag record timestamps, selecting by sensor time."""
    frames = list(frames)
    if not frames:
        raise PoseTimestampError("bag frame index is empty")
    if not math.isfinite(max_delta_sec) or max_delta_sec <= 0:
        raise PoseTimestampError("association max_delta_sec must be a positive number of seconds")
    if not math.isfinite(min_matched_ratio) or not 0 < min_matched_ratio <= 1:
        raise PoseTimestampError("association min_matched_ratio must be in (0, 1]")

    sensor_times = [row.timestamp for row in trajectory]
    rows: list[tuple[str, tuple[float, ...]]] = []
    deltas: list[float] = []
    matched_indices: list[int] = []
    unmatched_flags: list[bool] = []
    for frame in frames:
        frame_time = frame.sensor_time_ns / 1e9
        position = bisect.bisect_left(sensor_times, frame_time)
        best_index: int | None = None
        best_delta = math.inf
        for candidate in (position - 1, position):
            if 0 <= candidate < len(trajectory):
                delta = abs(sensor_times[candidate] - frame_time)
                if delta < best_delta:
                    best_index, best_delta = candidate, delta
        if best_index is None or best_delta > max_delta_sec:
            unmatched_flags.append(True)
            continue
        unmatched_flags.append(False)
        matched_indices.append(best_index)
        deltas.append(best_delta)
        rows.append((format_record_time(frame.record_time_ns), trajectory[best_index].values))

    matched = len(rows)
    total = len(frames)
    ratio = matched / total

    def _edge_unmatched(flags: list[bool]) -> tuple[int, int]:
        head = 0
        for flag in flags:
            if not flag:
                break
            head += 1
        tail = 0
        for flag in reversed(flags[head:]):
            if not flag:
                break
            tail += 1
        return head, tail

    head_unmatched, tail_unmatched = _edge_unmatched(unmatched_flags)
    interior_unmatched = sum(
        1 for index, flag in enumerate(unmatched_flags)
        if flag and head_unmatched <= index < total - tail_unmatched
    )

    duplicate_reuse = matched - len(set(matched_indices))
    non_monotonic = sum(
        1 for previous, current in zip(matched_indices, matched_indices[1:]) if current < previous
    )
    output_times = [row[0] for row in rows]
    output_increasing = all(b > a for a, b in zip(output_times, output_times[1:]))

    reject_reasons: list[str] = []
    if matched == 0:
        reject_reasons.append(
            "no native Pose sample could be associated to a bag frame within "
            f"{max_delta_sec:g} s; the trajectory and the bag do not share a time base"
        )
    elif ratio < min_matched_ratio:
        reject_reasons.append(
            f"matched_ratio {ratio:.6f} is below the required {min_matched_ratio:g} "
            f"({matched}/{total} bag frames associated within {max_delta_sec:g} s)"
        )
    if non_monotonic:
        reject_reasons.append(
            f"non_monotonic_match_count={non_monotonic}: native Pose order does not follow "
            "the bag record order"
        )
    if duplicate_reuse > max_duplicate_reuse_count:
        reject_reasons.append(
            f"duplicate_pose_reuse_count={duplicate_reuse} exceeds the allowed "
            f"{max_duplicate_reuse_count}; the Pose samples likely shifted by one frame or "
            "the frame rates do not match"
        )
    if rows and not output_increasing:
        reject_reasons.append("output timestamps are not strictly increasing")

    report: dict[str, Any] = {
        "method": ASSOCIATION_METHOD,
        "native_lookup_key": native_lookup_key,
        "output_lookup_key": output_lookup_key,
        "max_delta_sec": max_delta_sec,
        "min_matched_ratio": min_matched_ratio,
        "max_duplicate_reuse_count": max_duplicate_reuse_count,
        "bag_frame_count": total,
        "native_pose_count": len(trajectory),
        "matched_count": matched,
        "skipped_count": total - matched,
        "matched_ratio": round(ratio, 6),
        "mean_delta_sec": round(sum(deltas) / len(deltas), 9) if deltas else None,
        "max_delta_sec_observed": round(max(deltas), 9) if deltas else None,
        "head_unmatched_count": head_unmatched,
        "tail_unmatched_count": tail_unmatched,
        "interior_unmatched_count": interior_unmatched,
        "duplicate_pose_reuse_count": duplicate_reuse,
        "duplicate_pose_reuse_ratio": round(duplicate_reuse / matched, 6) if matched else 0.0,
        "non_monotonic_match_count": non_monotonic,
        "output_timestamps_strictly_increasing": output_increasing,
        "accepted": not reject_reasons,
        "reject_reasons": reject_reasons,
    }
    # A rejected association returns no rows at all: the caller must not be able
    # to publish a partial/wrong mapping by accident.  The report keeps every
    # statistic needed to understand the failure.
    return AssociationOutcome(
        accepted=not reject_reasons,
        rows=rows if not reject_reasons else [],
        report=report,
    )


def format_record_time(record_time_ns: int) -> str:
    """Nanosecond bag time as decimal seconds (9 fractional digits)."""
    return f"{record_time_ns / 1e9:.9f}"


def write_pose_trajectory(path: Path, rows: Iterable[tuple[str, tuple[float, ...]]]) -> int:
    """Write ``timestamp tx ty tz qx qy qz qw`` and return the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for timestamp, values in rows:
            handle.write(timestamp + " " + " ".join(f"{float(v):.9f}" for v in values) + "\n")
            count += 1
    return count


def write_association_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(report)
    payload.setdefault("generated_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_association_report(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
