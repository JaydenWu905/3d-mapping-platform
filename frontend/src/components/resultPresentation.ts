import type { ArtifactInfo, Manifest } from '../types';

export function readableNumber(value: number, digits = 2): string {
  return Number.isFinite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '—';
}
type Spec = [key: string, label: string, unit?: string, digits?: number];
const SPECS: Record<string, Spec[]> = {
  pose: [['pose_count','位姿数量','个',0],['native_pose_count','原始位姿数量','个',0],['bag_frame_count','输入点云帧数','帧',0],['matched_count','已关联帧数','帧',0],['matched_ratio','时间关联比例','%',2],['trajectory_length_m','轨迹长度','m',2],['loop_closures','回环数量','个',0]],
  surface: [['vertices','原生网格顶点','个',0],['faces','原生网格面片','个',0],['fused_frames','已融合帧数','帧',0],['selected_frames','选中帧数','帧',0],['skipped_no_pose_frames','缺少位姿的跳过帧','帧',0],['voxel_count','体素数量','个',0],['hash_point_count','哈希点数量','个',0],['preview_vertices','预览顶点','个',0],['preview_faces','预览面片','个',0]],
  distance: [['resolution_m','体素分辨率','m',3],['voxel_count','体素数量','个',0],['observed_voxel_count','已观测体素','个',0],['max_distance_m','最大距离','m',2],['truncation_distance_m','截断距离','m',2]],
};
export function coordinateRange(value: unknown): string | null {
  if (!Array.isArray(value) || value.length !== 2 || !value.every(row => Array.isArray(row) && row.length === 3 && row.every(v => typeof v === 'number' && Number.isFinite(v)))) return null;
  return ['X','Y','Z'].map((axis,i) => `${axis}：${readableNumber(value[0][i])} ～ ${readableNumber(value[1][i])} m`).join('\n');
}
/** Display-only selection and rounding; source manifests remain untouched. */
export function resultMetrics(stage: string, manifest: Manifest): { label: string; value: string }[] {
  const m = manifest.metrics || {};
  const rows: { label: string; value: string }[] = [];
  for (const [key,label,unit,digits] of SPECS[stage] || []) {
    const value = m[key];
    if (typeof value !== 'number' || !Number.isFinite(value)) continue;
    const number = unit === '%' ? value * 100 : value;
    const formatted = digits === 0 && !Number.isInteger(number) ? String(number) : readableNumber(number, digits);
    rows.push({ label, value: `${formatted}${unit ? ` ${unit}` : ''}` });
  }
  for (const [key,label] of [['preview_source_bounds','原生坐标范围'],['preview_bounds','预览坐标范围']] as const) {
    const value = coordinateRange(m[key]); if (value) rows.push({ label, value });
  }
  if (Array.isArray(m.bbox_m) && m.bbox_m.length === 3 && m.bbox_m.every(v => typeof v === 'number' && Number.isFinite(v))) rows.push({label:'空间尺寸',value:`${m.bbox_m.map(v => readableNumber(v as number)).join(' × ')} m`});
  if (Number.isFinite(manifest.runtime_sec)) rows.push({label:'阶段运行耗时',value:`${readableNumber(manifest.runtime_sec)} 秒`});
  return rows;
}
const ARTIFACT_NAMES: Record<string,string> = {
  trajectory_model:'轨迹预览',trajectory_raw:'轨迹数据',registered_trajectory:'已关联位姿轨迹',glim_native_trajectory:'GLIM 原生轨迹',pose_timestamp_association:'时间关联记录',glim_bag_frame_index:'输入帧索引',glim_effective_config:'位姿算法配置',glim_run_log:'位姿运行日志',
  surface_mesh:'原生 Mesh（PLY）',voxel_points:'原生体素数据',hash_points:'哈希点数据',run_config:'重建配置',frame_accounting:'帧处理统计',fused_frame_ledger:'已融合帧清单',navigation_input:'下阶段输入数据',
  esdf_map:'原生距离场地图',tsdf_map:'原生 TSDF 地图',slices_archive:'距离场切片压缩包',gradient:'距离梯度预览',slice_xy:'XY 距离切片',slice_xz:'XZ 距离切片',slice_yz:'YZ 距离切片',observed_xy:'XY 观测掩码',observed_xz:'XZ 观测掩码',observed_yz:'YZ 观测掩码',
};
export function artifactLabel(a: ArtifactInfo, manifest: Manifest): string {
  if (a.artifact_id === 'surface_model') return manifest.metrics?.preview_simplification_applied === true ? '简化 GLB 预览' : 'GLB 模型预览';
  return ARTIFACT_NAMES[a.artifact_id] || a.path.split('/').pop() || a.artifact_id;
}
export function previewDescription(stage: string, manifest: Manifest): string {
  if (stage === 'pose') return '轨迹预览可旋转、缩放和平移，原始轨迹文件见“下载”。';
  if (stage === 'surface') return manifest.metrics?.preview_simplification_applied === true ? '当前为简化 GLB 预览；完整原生 Mesh 在“下载”中单独提供。' : '模型预览可旋转、缩放和平移，原生文件见“下载”。';
  return '可切换方向查看距离场切片；未知区域不表示已确认安全。';
}
