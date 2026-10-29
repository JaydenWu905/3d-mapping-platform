# Distance/ESDF 阶段前端可视化重构（3D 点云查看器 / 切片元信息 / 原生产物下载）

- 状态：已实现并经真实任务 + demo 任务端到端验证（浏览器自动化 + 后端 API）
- 影响范围：Distance（ESDF）阶段的产物契约、`esdf_postprocess` 后处理、demo 演示数据、前端详情页距离阶段查看器
- 关联文档：`docs/distance-stage-web-preview-20261029.md`（新增产物与 `slices_meta.json` 字段级参考）

---

## 1. 背景与要解决的问题

改造前，Distance 阶段在前端只有「三张静态红蓝切片」，存在三个缺口：

| # | 问题 | 具体表现 |
| --- | --- | --- |
| 1 | 原生产物不可下载 | `esdf_vis.ply` 在 manifest 里是 `download: false`，页面只能看不能取，用户无法用 MeshLab 等专业工具核对 |
| 2 | 切片图没有物理含义 | 只有一张热力图，没有体素分辨率、坐标范围、切片位置、真实距离区间；"白色 = 无有效预览采样"也没有任何提示 |
| 3 | 缺少三维视图 | 全空间 ESDF 只有 XY/XZ/YZ 三个二维切片，无法整体观察空间结构 |

## 2. 关键约束

真实任务 `job_test_real` 的 `preview/esdf_vis.ply`：

```
format  : ASCII PLY
element : vertex 17706444        # 1770 万点
size    : 567,324,232 B          # 541 MiB
props   : x y z distance red green blue
```

这份文件**不可能**直接交给浏览器解析（`np.loadtxt` 都要分钟级，JS 侧更慢且会撑爆内存）。
因此方案确定为：**服务端生成浏览器专用降采样产物 + 原始文件只提供下载**，而不是前端硬解。

## 3. 方案总览

```
                        ┌────────────── 改造前 ──────────────┐
  C++ ESDF  ──►  preview/esdf_vis.ply       (567MB, 不可下载)
                 preview/slice_{xy,xz,yz}.png (裸图, 无元信息)
                 manifest: download=false
                        └────────────────────────────────────┘

                        ┌────────────── 改造后 ──────────────┐
  C++ ESDF  ──►  preview/esdf_vis.ply        → download=true（MeshLab 可开）
                 preview/esdf_vis_web.ply    → 新增：二进制降采样 40 万点 / 7.25MB（页面 3D 用）
                 preview/slice_*.png         → 不变（渲染逻辑未动，像素级与已验收一致）
                 preview/slices_meta.json    → 新增：几何 / 分辨率 / 距离范围 / web 预览信息
                 result_manifest.json        → metrics.slices_meta 内嵌整份元信息
                        └────────────────────────────────────┘

  前端 EsdfViewer：3 个切片页签 + 新增第 4 个「3D 点云」页签（懒加载）+ 切片下方元信息条
```

设计取舍：

- **不使用 Potree / visus / LOD 方案**：40 万点用 three `PLYLoader` 解析仅 127.7ms（实测），LOD 属于过度设计；
- **不新增下载 API**：下载完全由 manifest 的 `download` 字段驱动，符合项目契约（不改后端路由）；
- **切片渲染代码保持不动**：`render_slice()` 只增加"顺便返回元信息"，避免影响已验收的图面效果。

## 4. 后端改动（算法脚本层）

### 4.1 `backend/scripts/esdf_postprocess.py`（+145 行）

新增/修改要点：

1. **常量集中**：`LEGEND_D_MIN = -1.5`、`LEGEND_D_MAX = 1.5`、`PLANE_AXES = {"xy": ("x","y","z"), "xz": ("x","z","y"), "yz": ("y","z","x")}`，把图例范围与"平面→轴"映射从散落字面量收敛为单一事实源。
2. **`render_slice()` 返回元信息**：除写 PNG 外，额外返回 `u_range / v_range / distance_range / distance_range_observed / image_size_px / pixel_size_m / image_orientation`。
3. **新增 `write_web_preview(data, out_ply, max_points, seed=0)`**：
   - 超过 `max_points` 时按 `np.random.default_rng(seed)` 均匀抽样（默认 400000 点）；
   - 写 **binary_little_endian PLY**，属性 `x y z distance` + `uchar red green blue`；
   - 颜色与切片同源（红 −1.5 → 紫 0 → 蓝 +1.5），保证二维与三维观感一致；
   - 返回 `point_count / source_point_count / downsample_ratio / size_bytes / distance_range_observed / bounds_m`。
4. **`main()` 新增参数**：`--web_max_points`（默认 400000，0 表示不降采样）、`--skip_web_preview`（跳过 3D 产物）。
5. **`slices_meta.json` 结构升级**（schema_version 1.0）：

```json
{
  "schema_version": "1.0",
  "unit": "meter",
  "image_resolution_px": 480,
  "distance_legend_range_m": [-1.5, 1.5],
  "preview_abs_distance_max_m": 1.5,
  "bounds_m": {"x": [-54.0, 46.9], "y": [-33.6, 41.8], "z": [-10.6, 15.2]},
  "planes": {
    "xy": {
      "file": "slice_xy.png",
      "u_axis": "x", "v_axis": "y", "normal_axis": "z",
      "u_range": [-53.9, 46.4], "v_range": [-32.2, 27.3],
      "pixel_size_m": 0.209,
      "distance_range": [-1.5, 1.5],
      "distance_range_observed": [-0.4, 1.5],
      "center_m": 1.8, "half_thickness_m": 0.1, "thickness_m": 0.2,
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
    "bounds_m": {"x": [-54.0, 46.9], "y": [-33.6, 41.8], "z": [-10.6, 15.2]}
  }
}
```

6. **健壮性**：`write_web_preview` 用 `try/except` 包裹 —— 3D 预览生成失败只打印降级日志，切片与下载产物照常产出，不拖垮整个 Distance 阶段。

### 4.2 `backend/scripts/distance_run.py`（+11 行）

- `esdf_vis_ply` 的 `download` 由 `False` 改为 **`True`**（任务一的根因修复点）；
- 新增产物 `esdf_web_ply`（`role=preview`，`preview/esdf_vis_web.ply`，`download=False`）；文件不存在时自动从 specs 中剔除并打印提示，避免"缺一个降采样文件就判阶段失败"；
- 新增产物 `slices_meta`（`role=data`，`preview/slices_meta.json`，`download=True`）；
- `metrics` 改为 `dict(resolution_m=h, slices=list(planes), slices_meta=<整份元信息>, **validation)`，并兼容新旧两种 meta 结构（`planes` 包装 / 平铺）。

最终产物顺序：`esdf_map → esdf_vis_ply → esdf_web_ply → slice_{xy,xz,yz} → slices_meta`。

### 4.3 `backend/scripts/make_demo_data.py`（+135 行）

demo 数据是 mock 种子（`mock_backend: true`），原本只有合成切片，没有点云。为了让 demo 也能演示"三维查看 + 下载"，补充：

- `_DEMO_SOLIDS`：16×16×3 房间外壳 + 4 个货箱/障碍；`_DEMO_SPHERES`：1 个球体障碍；
- `_demo_esdf_cloud(points=40000, max_abs_distance=1.2)`：按面积分配采样点、沿法线随机偏移、rgb 与切片同源；
- `_write_ascii_ply()`：写与真实产物同格式的 ASCII PLY（`x y z distance r g b`）；
- `_write_demo_clouds()`：一次产出 `esdf_vis.ply`（ASCII，1.62MB / 40,640 点）、`esdf_vis_web.ply`（二进制，0.77MB）与 `slices_meta.json`，并把 `esdf_vis_ply`（download=true）、`esdf_web_ply`、`slices_meta` 写进 demo manifest。

> 注意：demo **不生成 `map.esdf`**。该文件是 Voxblox protobuf 二进制，只能由真实 C++ 运行产生，伪造会误导下游。真实 `.esdf` 只在真实任务中出现。

## 5. 产物契约变化

| artifact_id | 改前 | 改后 |
| --- | --- | --- |
| `esdf_vis_ply` | preview，`download=false` | preview，**`download=true`**（ASCII PLY，MeshLab 可开） |
| `esdf_web_ply` | 不存在 | **新增** preview，二进制降采样点云（页面 3D 用，不可下载） |
| `slices_meta` | 不存在（无结构化元信息） | **新增** data，`download=true` |
| `metrics.slices_meta` | 不存在 | **新增**，整份 meta 内嵌，前端零额外请求 |
| `slices_meta.json` 结构 | `{xy,xz,yz}` 平铺、仅范围字段 | 新 schema（见 4.1），保留老格式兼容读取 |
| 切片 PNG | — | **未改**（像素级不变） |

兼容策略：

- 前端 `readSlicesMeta()` 同时接受新格式（`planes` 包装）与老任务平铺格式；
- 老 manifest 缺 `slices_meta` 时，元信息条退化为只显示「体素分辨率」一行，不报错；
- 老任务不会自动获得 3D 页签，需重跑一次后处理（命令见第 8 节），页面在产物缺失时优雅降级。

## 6. 前端改动

### 6.1 新增 `frontend/src/viewers/esdfMeta.ts`（139 行）

纯函数格式化层：

| 函数 | 作用 |
| --- | --- |
| `readSlicesMeta(metrics)` | 从 `manifest.metrics.slices_meta` 归一化新旧两种结构 |
| `planeMeta(meta, plane)` | 老数据缺 `u_axis/v_axis/normal_axis` 时按平面名补默认轴 |
| `formatAxisRanges(pairs, unit)` | `X [-53.9, 46.4] · Y [-32.2, 27.3] m`（单位只出现一次） |
| `formatCount(v)` | ≥ 1 万转「x.x 万」 |
| `sliceMetaRows()` | 体素分辨率 / 坐标范围 / 切片像素 / 切片位置 / 距离范围（含实际观测区间） |
| `cloudMetaRows()` | 预览点数 / 坐标范围 / 距离范围 / 预览文件大小 |

### 6.2 新增 `frontend/src/viewers/esdfPlyWorker.ts`（92 行）

- Web Worker 内 `PLYLoader.parse(ArrayBuffer)`，`setCustomPropertyNameMapping({ distance: ['distance'] })` 取出自定义属性；
- 世界 Z-up 转 three Y-up：`(x, z, -y)`；
- `postMessage(msg, [positions.buffer, distances.buffer, colors.buffer])` 零拷贝回传；
- 实测解析耗时：40,640 点 **25ms**；399,987 点 **127.7ms**。

### 6.3 新增 `frontend/src/viewers/PointCloudViewer.tsx`（200 行）

- r3f `<Canvas>` + `OrbitControls`（旋转 / 缩放 / 平移）+ `FitView`（按包围盒自动取景）；
- `ShaderMaterial` 按 `vDistance` 做红(−1.5) → 紫(0) → 蓝(+1.5) 映射，可切换「原始顶点色」；
- 工具栏：顶点色勾选、点大小滑杆（1–6px）、重置视角；
- 模块级 `cloudCache`：切页签不重复下载/解析；
- 底部信息条：左「拖拽旋转 · 滚轮缩放 · 右键平移 · 颜色 = 带符号距离」，右「点数 · 源点数（抽样率）」；`pointer-events: none` 不挡交互。

### 6.4 重构 `frontend/src/viewers/EsdfViewer.tsx`（+121 行）

- 页签：`xy / xz / yz` + 第 4 个「3D 点云」，仅当 manifest 存在 `esdf_web_ply` 时出现，点击才挂载（懒加载）；
- 二维分支（切片、观测掩码、梯度箭头 canvas）保持原逻辑，仅修正"无 gradient 产物时勾选态"（改为未选 + 禁用）；
- 新增 `<dl class="esdf-meta">` 元信息条：切片页显示切片物理含义，3D 页显示点云统计。

### 6.5 类型与接线

- `frontend/src/types/index.ts`（+54）：`AxisRange`、`SlicePlaneMeta`、`SlicesMeta`、`EsdfWebPreviewMeta`；
- `frontend/src/pages/JobDetailPage.tsx`（3 行）：把 `manifest.metrics` 传给 `EsdfViewer`；距离阶段提示改为「切片 / 3D 点云切换 · 原生地图与点云可下载」；
- `frontend/src/components/resultPresentation.ts`（2 行）：补 `esdf_vis_ply / esdf_web_ply / slices_meta` 的中文名，避免回退成文件名。

### 6.6 样式 `frontend/src/styles.css`（+116 行）

3D 舞台 `aspect-ratio: 16/10`；点云容器 / 加载态 / 错误态；底部信息条；工具栏深色化与滑杆宽度；元信息条由 grid 改为 `flex-wrap` 流式排布（解决窄宽度下参差换行）。

## 7. 增删改查一览

| 类别 | 内容 |
| --- | --- |
| **增** | 产物 `esdf_web_ply`、`slices_meta`；字段 `metrics.slices_meta`；文件 `esdfMeta.ts`、`esdfPlyWorker.ts`、`PointCloudViewer.tsx`、本文档；demo 合成点云（ASCII + 二进制）；`write_web_preview()`、`_demo_esdf_cloud()`、`_write_ascii_ply()`、`_write_demo_clouds()`；页签「3D 点云」；元信息条；3D 工具栏 |
| **删** | 移除「二维切片是唯一视图」的隐含假设；删除点云查看器里互相遮挡的 `.point-cloud-hud` / `.viewer-hint` 绝对定位层；删除 `.point-cloud-hud` / `.point-cloud-warn` 旧 CSS；元信息 grid 布局改为 flex；`slices_meta.json` 不再只有三个键、不再缺观测区间 |
| **改** | `esdf_vis_ply.download` false→true；`render_slice()` 增加返回 meta；`distance_run.py` 产物规格与 metrics；`EsdfViewer` props 增加 `metrics`；`metrics.slices` 统一为"平面名数组"；demo manifest 与 metrics；梯度箭头勾选态；距离阶段提示文案 |
| **查** | 前端只读 `manifest.metrics.slices_meta`（零额外请求）；点云走 `GET /api/jobs/{job}/stages/distance/previews/esdf_web_ply`；下载走 `GET .../artifacts/{id}`（仅 `download=true` 放行，支持 Range）；元信息文件本体走 `artifacts/slices_meta` |

## 8. 运行与验证

### 8.1 生成/重跑

```bash
# 完整 Distance 阶段（Linux / WSL）
bash backend/scripts/run_esdf.sh --job-dir jobs/<job> --backend voxel_esdf --mode full

# 只重跑后处理（老任务补 3D 预览与元信息）
python backend/scripts/esdf_postprocess.py \
  --input_ply  jobs/<job>/stage3_esdf/preview/esdf_vis.ply \
  --output_dir jobs/<job>/stage3_esdf/preview \
  --resolution 480 --web_max_points 400000
```

### 8.2 已验证结果

后端 / 契约：

- `GET /api/health` → `{"status":"ok"}`；
- `previews/esdf_web_ply` → 200 / 7,600,083 B / `application/octet-stream`；
- `artifacts/esdf_vis_ply` → Range 请求 `206`，`bytes 0-63/567324232`，首字节 `ply\nformat ascii 1.0`；
- 真实任务后处理：17,706,444 → 399,987 点（抽样 2.26%），7.25 MB。

构建：`npm run typecheck` 无 error；`npm run build` 通过（worker 独立 chunk 92.46 kB）。

浏览器端到端（puppeteer + Chrome，WebGL2）：

- 真实任务下载区：`esdf_map`、`slices_meta`、`esdf_vis_ply(567MB)` 可下载；`esdf_web_ply` 与切片标注"仅用于页面预览"；
- 切片元信息实测：`体素分辨率 0.1 m / 坐标范围 X [-53.9, 46.4] · Y [-32.2, 27.3] m / 切片像素 0.209 m/px · 480×480 px / 切片位置 Z = 1.8 ± 0.1 m · 29.1 万点 / 距离范围 [-1.5, 1.5] m（实际 [-0.4, 1.5] m）`；
- 3D 页：`399,987 点 · 源 17,706,444 点（抽样 2.3%）`；拖拽旋转前后截图哈希不同（交互生效）；顶点色切换生效；
- demo 任务：40,640 点房间/障碍点云；切片带观测掩码与梯度箭头；下载清单含 `esdf_vis.ply`（1,623,179 B）；
- 唯一控制台报错是既有的 `favicon.ico 404`。

## 9. 边界、风险与后续

1. **未改 `run_esdf.sh`**：它是薄壳（校验参数后 `exec distance_run.py`），`download` 开关真正在 `distance_run.py` 的产物规格里，改壳只会引入第二份事实源。
2. **未新增下载 API**：符合契约，`download` 字段即开关。
3. **demo 无 `map.esdf`**：见 4.3 说明，属刻意留白。
4. **老任务无 3D 页签**：需按 8.1 重跑后处理；缺失时前端降级显示。
5. **Windows 本机后端仍需 POSIX `fcntl`**（`backend/app/services/runner_adapter.py:19`，既有问题，本次未触碰）。
6. **大文件下载（567MB）无进度条**：FileResponse + Range 已可用；若要做进度/断点续传，建议单独开 issue。
7. **降采样点数可配**：默认 40 万（7.25MB）；如遇低配设备，可下调 `--web_max_points` 或在前端加"加载更多"分级。

## 10. 文件清单

| 类型 | 路径 |
| --- | --- |
| 修改 | `backend/scripts/esdf_postprocess.py`、`backend/scripts/distance_run.py`、`backend/scripts/make_demo_data.py` |
| 修改 | `frontend/src/viewers/EsdfViewer.tsx`、`frontend/src/types/index.ts`、`frontend/src/pages/JobDetailPage.tsx`、`frontend/src/components/resultPresentation.ts`、`frontend/src/styles.css` |
| 新增 | `frontend/src/viewers/PointCloudViewer.tsx`、`frontend/src/viewers/esdfPlyWorker.ts`、`frontend/src/viewers/esdfMeta.ts` |
| 新增 | `docs/distance-stage-web-preview-20261029.md`、本文档 |
| 新增（demo 数据） | `demo_jobs/demo_room/stage3_esdf/esdf_vis.ply`、`esdf_vis_web.ply`、`slices_meta.json` |
| 修改（demo 数据） | `demo_jobs/demo_room/stage3_esdf/result_manifest.json`、`progress.json`、`gradient.json`、`slices/*.png`、`slices.zip` |
