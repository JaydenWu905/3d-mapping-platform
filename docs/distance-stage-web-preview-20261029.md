# Distance 阶段网页预览契约补充（3D 点云 / 切片元信息）

本文件补充 `docs/surface-to-distance-manifest-v0.md` 与 `docs/distance-surface-contract-20261021.md`：
Distance 阶段的产物清单新增了网页专用降采样点云与结构化切片元信息，原始 `esdf_vis.ply` 同时改为可下载。

## 1. 产物清单变化

| artifact_id | role | path | content_type | download | 说明 |
| --- | --- | --- | --- | --- | --- |
| `esdf_map` | data | `map.esdf` | `application/octet-stream` | 是 | 原生二进制距离场，规划侧权威输入 |
| `esdf_vis_ply` | preview | `preview/esdf_vis.ply` | `application/octet-stream` | **是（原为否）** | 全量可视化点云（ASCII PLY，含 `x y z distance red green blue`），供 MeshLab 等外部工具打开 |
| `esdf_web_ply` | preview | `preview/esdf_vis_web.ply` | `application/octet-stream` | 否 | 浏览器 3D 视图专用降采样点云（二进制小端 PLY，默认 ≤ 40 万点） |
| `slice_<plane>` | preview | `preview/slice_<plane>.png` | `image/png` | 否 | 三视图切片 |
| `slices_meta` | data | `preview/slices_meta.json` | `application/json` | 是 | 切片几何/分辨率/距离范围等元信息，同时整份嵌入 `metrics.slices_meta` |

下载走既有 `GET /api/jobs/{job_id}/stages/{stage}/artifacts/{artifact_id}`，只由 manifest 的 `download` 字段控制，没有新增下载 API。

## 2. `slices_meta.json` 结构（schema_version 1.0）

```json
{
  "schema_version": "1.0",
  "unit": "meter",
  "image_resolution_px": 480,
  "distance_legend_range_m": [-1.5, 1.5],
  "preview_abs_distance_max_m": 1.5,
  "bounds_m": { "x": [-54.0, 46.9], "y": [-33.6, 41.8], "z": [-10.6, 15.2] },
  "planes": {
    "xy": {
      "file": "slice_xy.png",
      "u_axis": "x", "v_axis": "y", "normal_axis": "z",
      "u_range": [-53.9, 46.4],
      "v_range": [-32.2, 27.3],
      "pixel_size_m": 0.209,
      "distance_range": [-1.5, 1.5],
      "distance_range_observed": [-0.4, 1.5],
      "center_m": 1.8,
      "half_thickness_m": 0.1,
      "thickness_m": 0.2,
      "sampled_points": 290915,
      "image_size_px": [480, 480],
      "image_orientation": "row0=v_max",
      "unknown_color": "white",
      "unit": "meter"
    }
  },
  "web_preview": {
    "artifact_id": "esdf_web_ply",
    "format": "binary_little_endian PLY",
    "point_count": 399987,
    "source_point_count": 17706444,
    "downsample_ratio": 0.0226,
    "size_bytes": 7600083,
    "distance_range": [-1.5, 1.5],
    "distance_range_observed": [-0.4, 1.5],
    "bounds_m": { "x": [-54.0, 46.9], "y": [-33.6, 41.8], "z": [-10.6, 15.2] }
  }
}
```

兼容性：旧任务的 `slices_meta.json` 是平铺的 `{ "xy": {...}, "xz": {...}, "yz": {...} }` 且没有 `planes` 包装，
前端 `frontend/src/viewers/esdfMeta.ts` 的 `readSlicesMeta()` 两种都接受；缺 `slices_meta` 的老 manifest 只退化到
「体素分辨率」一行。

## 3. 前端消费方式

- `frontend/src/viewers/EsdfViewer.tsx`：切片页签下方用 `<dl class="esdf-meta">` 展示 `slices_meta` 推导出的行；
  第四个页签「3D 点云」只在存在 `esdf_web_ply` 产物时出现，点击后才挂载 `PointCloudViewer`（懒加载）。
- `frontend/src/viewers/esdfPlyWorker.ts`：Web Worker 内用 three `PLYLoader` 解析二进制 PLY，把
  `position`（世界 Z-up 转 three Y-up：`(x, z, -y)`）、`distance`、`color` 以 transferable 回传主线程。
- `frontend/src/viewers/PointCloudViewer.tsx`：`ShaderMaterial` 按 `distance` 在红(−1.5)→紫(0)→蓝(+1.5) 上映射，
  也支持切回顶点色；`FitView` 自动对准包围盒，`OrbitControls` 提供旋转/缩放/平移。

## 4. 生成方式

`run_esdf.sh` → `distance_run.py` → `esdf_postprocess.py`：

```bash
python backend/scripts/esdf_postprocess.py \
  --input_ply  <stage3_esdf>/preview/esdf_vis.ply \
  --output_dir <stage3_esdf>/preview \
  --resolution 480 \
  --web_max_points 400000
```

`--web_max_points 0` 表示不降采样（demo 数据走这条路径，4 万点全部保留）；
`--skip_web_preview` 可跳过 `esdf_vis_web.ply` 生成。
