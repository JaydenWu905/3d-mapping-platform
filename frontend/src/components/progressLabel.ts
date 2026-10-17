import type { StageDetail } from '../types';

export type ProgressBarState = {
  percent: number | null;
  kind: 'input' | 'stage';
  busy: boolean;
};

export function progressBarState(stage: StageDetail): ProgressBarState {
  const active = stage.status === 'running' || stage.status === 'queued' || stage.status === 'cancelling';
  if (stage.stage !== 'pose' || stage.backend !== 'glim' || stage.status === 'completed') {
    return { percent: Math.max(0, Math.min(100, stage.progress || 0)), kind: 'stage', busy: false };
  }
  const total = stage.lidar_total ?? 0;
  const published = stage.lidar_published ?? 0;
  const publishing = stage.phase === 'input_publishing';
  const publishedDone = stage.phase === 'waiting_glim_export' || stage.phase === 'associating';
  if (total > 0 && (publishing || publishedDone || published > 0)) {
    return {
      percent: publishedDone ? 100 : Math.max(0, Math.min(100, published / total * 100)),
      kind: 'input',
      busy: active && publishedDone,
    };
  }
  return { percent: null, kind: 'input', busy: active };
}

export function progressLabel(stage: StageDetail): string {
  const metrics = stage.manifest?.metrics;
  if (stage.stage === 'pose' && metrics?.pose_count != null) {
    return `输出 ${metrics.pose_count} 位姿 · 全包 ${metrics.bag_frame_count ?? '—'} 帧`;
  }
  if (stage.stage === 'pose') {
    if (stage.phase === 'input_publishing' || stage.phase === 'waiting_glim_export' || stage.phase === 'associating') {
      const lidar = stage.lidar_published ?? 0;
      const total = stage.lidar_total ?? 0;
      const ratio = total > 0 ? `（输入发布进度 ${Math.round(progressBarState(stage).percent ?? 0)}%）` : '';
      return `LiDAR 已发布 ${lidar}/${total || '总量未知'} ${ratio} · IMU 已发布 ${stage.imu_published ?? 0}${stage.imu_total ? `/${stage.imu_total}` : ''}`;
    }
    return stage.status === 'failed' ? 'Pose 失败' : '等待执行 / 启动 GLIM';
  }
  if (!stage.total) return '未上报帧进度';
  return `${stage.current} / ${stage.total} ${stage.unit || ''}`;
}

export function posePhaseLabel(stage: StageDetail): string {
  if (stage.status === 'completed') return 'Pose 完成';
  if (stage.status === 'failed' || stage.status === 'cancelled') return stage.status === 'failed' ? 'Pose 失败' : 'Pose 已取消';
  switch (stage.phase) {
    case 'input_publishing': return '输入发布';
    case 'waiting_glim_export': return '输入发布完成，正在等待 GLIM 导出';
    case 'associating': return '轨迹关联与产物生成';
    default: return '等待执行 / 启动 GLIM';
  }
}

export function stageProgressText(stage: StageDetail): string {
  return stage.stage === 'pose' && stage.backend === 'glim' && stage.status !== 'completed'
    ? posePhaseLabel(stage)
    : `阶段 ${Math.round(stage.progress)}%`;
}
