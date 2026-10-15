import type { StageDetail } from '../types';

export function progressLabel(stage: StageDetail): string {
  const metrics = stage.manifest?.metrics;
  if (stage.stage === 'pose' && metrics?.pose_count != null) {
    return `输出 ${metrics.pose_count} 位姿 · 全包 ${metrics.bag_frame_count ?? '—'} 帧`;
  }
  if (!stage.total) return '未上报帧进度';
  return `${stage.current} / ${stage.total} ${stage.unit || ''}`;
}
