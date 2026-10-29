/**
 * 距离场点云解析 Worker。
 *
 * 后端 esdf_postprocess.py 额外导出的 preview/esdf_vis_web.ply 是「二进制 + 降采样」版本
 * （默认 40 万点 ≈ 7.6 MB）。原始 esdf_vis.ply（1770 万点 / 567 MB ASCII）只用于下载，
 * 不进入浏览器 —— 那是这个模块唯一的性能红线。
 *
 * 解析放在 Worker 里做：three 的 PLYLoader 对二进制 PLY 仍会逐点构造 JS 对象，
 * 40 万点足以在主线程造成明显卡顿，所以整段解析 + 坐标变换都离开 UI 线程。
 */
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js';

export interface ParsedPointCloud {
  /** three 坐标系（Y-up）下的顶点位置，已从世界坐标 (x, y, z) 转成 (x, z, -y)。 */
  positions: Float32Array;
  /** 每个点到最近表面的符号距离（米），缺失时全 0。 */
  distances: Float32Array;
  /** 0-255 的顶点颜色，缺失时全白。 */
  colors: Uint8Array;
  pointCount: number;
  hasDistance: boolean;
  hasColor: boolean;
}

export interface PointCloudRequest {
  url: string;
}

export type PointCloudResponse =
  | ({ ok: true } & ParsedPointCloud)
  | { ok: false; error: string };

// tsconfig 只带 DOM lib，这里用最小结构声明 Worker 全局，避免引入 WebWorker lib 与 DOM 冲突。
const workerScope = self as unknown as {
  postMessage: (message: unknown, transfer?: Transferable[]) => void;
  onmessage: ((event: MessageEvent<PointCloudRequest>) => void) | null;
};

function parsePointCloud(buffer: ArrayBuffer): ParsedPointCloud {
  const loader = new PLYLoader();
  // 让 PLYLoader 把自定义属性 distance 保留成 BufferAttribute，供着色调色使用。
  loader.setCustomPropertyNameMapping({ distance: ['distance'] });
  const geometry = loader.parse(buffer);
  const position = geometry.getAttribute('position');
  if (!position || position.count === 0) throw new Error('PLY 中没有顶点数据');

  const count = position.count;
  const positions = new Float32Array(count * 3);
  const source = position.array as ArrayLike<number>;
  for (let i = 0; i < count; i += 1) {
    const x = source[i * 3];
    const y = source[i * 3 + 1];
    const z = source[i * 3 + 2];
    // 世界坐标 Z-up → three Y-up
    positions[i * 3] = x;
    positions[i * 3 + 1] = z;
    positions[i * 3 + 2] = -y;
  }

  const distanceAttribute = geometry.getAttribute('distance');
  const distances = new Float32Array(count);
  if (distanceAttribute && distanceAttribute.count === count) {
    distances.set(distanceAttribute.array as ArrayLike<number>);
  }

  const colorAttribute = geometry.getAttribute('color');
  const colors = new Uint8Array(count * 3);
  if (colorAttribute && colorAttribute.count === count) {
    const array = colorAttribute.array as ArrayLike<number>;
    // three 可能给 0-1 的归一化浮点，也可能给 0-255 的 uchar；按采样最大值判断。
    let peak = 0;
    const probe = Math.min(array.length, 3000);
    for (let i = 0; i < probe; i += 1) peak = Math.max(peak, array[i]);
    const scale = peak <= 1.0001 ? 255 : 1;
    for (let i = 0; i < count * 3; i += 1) colors[i] = Math.round(array[i] * scale);
  } else {
    colors.fill(255);
  }

  geometry.dispose();
  return {
    positions,
    distances,
    colors,
    pointCount: count,
    hasDistance: Boolean(distanceAttribute),
    hasColor: Boolean(colorAttribute),
  };
}

workerScope.onmessage = (event: MessageEvent<PointCloudRequest>) => {
  const { url } = event.data;
  fetch(url)
    .then((response) => {
      if (!response.ok) throw new Error(`点云下载失败：HTTP ${response.status}`);
      return response.arrayBuffer();
    })
    .then((buffer) => {
      const parsed = parsePointCloud(buffer);
      workerScope.postMessage(
        { ok: true, ...parsed } satisfies PointCloudResponse,
        [parsed.positions.buffer, parsed.distances.buffer, parsed.colors.buffer],
      );
    })
    .catch((error: unknown) => {
      workerScope.postMessage({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      } satisfies PointCloudResponse);
    });
};
