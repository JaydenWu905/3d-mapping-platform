import type { StageDetail } from '../../types';

/**
 * 真实预览只按产物判断；不用进度百分比猜测结果是否已经可用。
 * 等待预览与查看器切换共用同一套判据。
 */
export function hasUsablePreview(stage: StageDetail): boolean {
  const artifactIds = new Set(
    stage.manifest?.artifacts?.map((artifact) => artifact.artifact_id) ?? [],
  );
  if (stage.stage === 'pose') return artifactIds.has('trajectory_model');
  if (stage.stage === 'surface') return artifactIds.has('surface_model');
  if (stage.stage === 'distance') {
    return ['xy', 'xz', 'yz'].some((plane) => artifactIds.has(`slice_${plane}`));
  }
  return false;
}
