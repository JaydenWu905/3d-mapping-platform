import type { AxisRange, SlicePlaneMeta, SlicesMeta } from '../types';

const PLANES = ['xy', 'xz', 'yz'] as const;
/** 老格式缺 axis 字段时按平面名补默认轴。 */
const DEFAULT_AXES: Record<string, [string, string, string]> = {
  xy: ['x', 'y', 'z'],
  xz: ['x', 'z', 'y'],
  yz: ['y', 'z', 'x'],
};

/**
 * 从 manifest.metrics 读取切片元信息。
 * 新格式是 { planes: { xy: {...} } }，老任务是平铺的 { xy: {...} }，两种都认。
 */
export function readSlicesMeta(metrics: Record<string, unknown> | null | undefined): SlicesMeta | null {
  const raw = metrics?.slices_meta;
  if (!raw || typeof raw !== 'object') return null;
  const meta = raw as SlicesMeta;
  if (meta.planes && typeof meta.planes === 'object' && Object.keys(meta.planes).length > 0) return meta;
  const legacy: Record<string, SlicePlaneMeta> = {};
  for (const plane of PLANES) {
    const value = (raw as Record<string, unknown>)[plane];
    if (value && typeof value === 'object') legacy[plane] = value as SlicePlaneMeta;
  }
  return Object.keys(legacy).length > 0 ? { ...meta, planes: legacy } : null;
}

export function planeMeta(meta: SlicesMeta | null, plane: string): SlicePlaneMeta | null {
  const info = meta?.planes?.[plane];
  if (!info) return null;
  const [uAxis, vAxis, normalAxis] = DEFAULT_AXES[plane] ?? ['u', 'v', 'w'];
  return {
    ...info,
    u_axis: info.u_axis ?? uAxis,
    v_axis: info.v_axis ?? vAxis,
    normal_axis: info.normal_axis ?? normalAxis,
  };
}

function round(value: number, digits = 2): string {
  return String(Number(value.toFixed(digits)));
}

function validRange(range: AxisRange | undefined): range is AxisRange {
  return Array.isArray(range) && range.length === 2 && range.every((v) => typeof v === 'number' && Number.isFinite(v));
}

function formatInterval(range: AxisRange): string {
  return `[${round(range[0])}, ${round(range[1])}] m`;
}

/** 坐标范围合并成一项：X [-53.9, 46.4] · Y [-32.2, 27.3] m（单位只在末尾出现一次）。 */
function formatAxisRanges(pairs: { axis: string; range: AxisRange }[], unit = 'm'): string {
  return `${pairs.map(({ axis, range }) => `${axis.toUpperCase()} [${round(range[0])}, ${round(range[1])}]`).join(' · ')} ${unit}`;
}

export function formatCount(value: number): string {
  if (value >= 10000) return `${round(value / 10000, 1)} 万`;
  return String(Math.round(value));
}

export interface MetaRow {
  label: string;
  value: string;
}

/** 当前切片的物理含义：坐标范围、分辨率、切片位置、距离范围。 */
export function sliceMetaRows(
  plane: string,
  meta: SlicesMeta | null,
  voxelResolutionM?: number,
): MetaRow[] {
  const info = planeMeta(meta, plane);
  const rows: MetaRow[] = [];
  if (voxelResolutionM && Number.isFinite(voxelResolutionM)) {
    rows.push({ label: '体素分辨率', value: `${round(voxelResolutionM, 3)} m` });
  }
  if (!info) return rows;

  const u = (info.u_axis ?? 'u').toUpperCase();
  const v = (info.v_axis ?? 'v').toUpperCase();
  if (validRange(info.u_range) && validRange(info.v_range)) {
    rows.push({
      label: '坐标范围',
      value: formatAxisRanges([
        { axis: u, range: info.u_range },
        { axis: v, range: info.v_range },
      ]),
    });
  }

  const pixel: string[] = [];
  if (typeof info.pixel_size_m === 'number' && Number.isFinite(info.pixel_size_m)) {
    pixel.push(`${round(info.pixel_size_m, 3)} m/px`);
  }
  if (Array.isArray(info.image_size_px) && info.image_size_px.length === 2) {
    pixel.push(`${info.image_size_px[0]}×${info.image_size_px[1]} px`);
  }
  if (pixel.length > 0) rows.push({ label: '切片像素', value: pixel.join(' · ') });

  const normal = (info.normal_axis ?? 'w').toUpperCase();
  if (typeof info.center_m === 'number' && Number.isFinite(info.center_m)) {
    const half = typeof info.half_thickness_m === 'number' && Number.isFinite(info.half_thickness_m) ? ` ± ${round(info.half_thickness_m)}` : '';
    const sampled = typeof info.sampled_points === 'number' ? ` · ${formatCount(info.sampled_points)}点` : '';
    rows.push({ label: '切片位置', value: `${normal} = ${round(info.center_m)}${half} m${sampled}` });
  }

  const legend = validRange(info.distance_range)
    ? info.distance_range
    : validRange(meta?.distance_legend_range_m)
      ? (meta?.distance_legend_range_m as AxisRange)
      : null;
  if (legend) {
    const observed = validRange(info.distance_range_observed)
      ? `（实际 ${formatInterval(info.distance_range_observed)}）`
      : '';
    rows.push({ label: '距离范围', value: `${formatInterval(legend)}${observed}` });
  }
  return rows;
}

/** 3D 点云标签页的元信息：点数、坐标范围、距离范围、文件大小。 */
export function cloudMetaRows(meta: SlicesMeta | null): MetaRow[] {
  const web = meta?.web_preview;
  const rows: MetaRow[] = [];
  if (!web) return rows;

  if (typeof web.point_count === 'number' && Number.isFinite(web.point_count)) {
    const source = typeof web.source_point_count === 'number' && web.source_point_count !== web.point_count
      ? ` / 原始 ${formatCount(web.source_point_count)}点`
      : '';
    rows.push({ label: '预览点数', value: `${formatCount(web.point_count)}点${source}` });
  }

  const bounds = web.bounds_m ?? meta?.bounds_m;
  if (bounds) {
    const pairs = (['x', 'y', 'z'] as const).flatMap((axis) => {
      const range = bounds[axis];
      return validRange(range) ? [{ axis, range }] : [];
    });
    if (pairs.length > 0) rows.push({ label: '坐标范围', value: formatAxisRanges(pairs) });
  }

  const legend = validRange(web.distance_range)
    ? web.distance_range
    : validRange(meta?.distance_legend_range_m)
      ? (meta?.distance_legend_range_m as AxisRange)
      : null;
  if (legend) {
    const observed = validRange(web.distance_range_observed)
      ? `（实际 ${formatInterval(web.distance_range_observed)}）`
      : '';
    rows.push({ label: '距离范围', value: `${formatInterval(legend)}${observed}` });
  }

  if (typeof web.size_bytes === 'number' && web.size_bytes > 0) {
    rows.push({ label: '预览文件', value: `${round(web.size_bytes / 1024 / 1024, 1)} MB · 二进制 PLY` });
  }
  return rows;
}
