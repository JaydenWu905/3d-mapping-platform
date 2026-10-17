import type { StageDetail, StageProgressEvent } from '../types';

/** Copy only fields present in an SSE update; absent counters keep their last value. */
export function stageProgressPatch(data: StageProgressEvent): Partial<StageDetail> {
  const patch: Partial<StageDetail> = {};
  if (data.status) patch.status = data.status as StageDetail['status'];
  if (data.phase !== undefined) patch.phase = data.phase;
  if (data.progress !== undefined) patch.progress = data.progress;
  if (data.current !== undefined) patch.current = data.current;
  if (data.total !== undefined) patch.total = data.total;
  if (data.unit !== undefined) patch.unit = data.unit;
  if (data.message !== undefined) patch.message = data.message;
  if (data.elapsed_sec !== undefined) patch.elapsed_sec = data.elapsed_sec;
  if (data.lidar_published !== undefined) patch.lidar_published = data.lidar_published;
  if (data.lidar_total !== undefined) patch.lidar_total = data.lidar_total;
  if (data.imu_published !== undefined) patch.imu_published = data.imu_published;
  if (data.imu_total !== undefined) patch.imu_total = data.imu_total;
  if (data.input_updated_at !== undefined) patch.input_updated_at = data.input_updated_at;
  return patch;
}
