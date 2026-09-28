# 三模块三维建图系统

三维建图平台：**位姿估计（Pose/SLAM）→ 稠密建面（Surface）→ 距离场（ESDF）** 三阶段流水线的
**网页展示 + 轻量调度** 框架。

平台同时支持两类执行路径：`demo_room` 使用 Mock Runner 演示完整三阶段；注册的 Oxford
LiDAR 数据使用真实子进程链路，执行
`registered_pose_import → Surface input preparation → MrHash-LiDAR`。其中 Pose backend
只验证并导入数据集已注册的预计算 Pose，**不是本次运行 GLIM**。真实 GLIM、H3-Mapping 和
真实 ESDF Runner 尚未接入。MrHash RGB-D 官方入口已经确认，平台侧接口和校验框架已经准备，
但运行时映射仍为 disabled / Not Ready。

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  前端 (React + TS + Vite)    端口 5173                       │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ 任务列表  │→│ 新建任务      │→│ 任务详情 3D 预览        │ │
│  └──────────┘  │ 选择算法      │  │ ① 位姿轨迹  ② 网格  ③ ESDF │
│                └──────────────┘  └────────────────────────┘ │
│  所有查看器按“阶段键 → 查看器”固定映射，前端不认识任何算法名 │
└──────────────────────┬──────────────────────────────────────┘
        REST + SSE（/api 代理）
┌──────────────────────┴──────────────────────────────────────┐
│  后端 (FastAPI)      127.0.0.1:8000                          │
│  ┌──────────────────┐  ┌──────────────────────────────────┐  │
│  │ 调度器            │  │ Mock / 真实子进程 Runner         │  │
│  │ 阶段状态机        │  │ 生成 trajectory.json / *.glb /   │  │
│  │ 取消/重跑/失败    │  │ 切片 png / gradient.json / manifest │  │
│  └──────────────────┘  └──────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                jobs/（JSON + 文件，刷新后状态可恢复）
```

### 三条架构红线（约束，已落实为代码事实）

| 红线 | 落实方式 |
|---|---|
| 前端不执行 shell、不理解 Conda/Pixi/ROS、不硬编码算法路径 | 前端只用 `api.ts` 发 HTTP；查看器只认 `artifact_id`，不做 `backend === 'GLIM'` 之类分支 |
| 不针对每个算法复制页面 | 阶段键 → 查看器是**固定映射**（pose→轨迹、surface→网格、distance→切面） |
| 严禁任意文件路径下载 / 路径穿越 | 取文件一律 `artifact_id`；后端三步校验见 *安全模型* |

---

## 二、目录结构

```
3d-mapping-platform/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口（/api）
│   │   ├── api/               # 路由：jobs / stages / previews / artifacts / events
│   │   ├── models/            # Pydantic 模型
│   │   └── services/          # 调度器、Mock/子进程 Runner、磁盘状态
│   ├── config/                # backend 与服务器受控 dataset 注册信息
│   ├── scripts/               # Mock/真实算法子进程入口与适配器
│   ├── requirements.txt
│   ├── run_backend.bat        # 一键启动后端（自动建 venv）
│   └── ...
├── frontend/
│   ├── src/
│   │   ├── api/api.ts         # 全部 HTTP 入口（URL 只由 artifact_id 构造）
│   │   ├── types/index.ts     # 与后端模型一一对应的类型 + SSE 事件
│   │   ├── hooks/useJob.ts    # REST 全量 + EventSource 增量
│   │   ├── components/        # StageCard / PipelineView / LogViewer / ArtifactsPanel…
│   │   ├── viewers/           # TrajectoryViewer / MeshViewer / EsdfViewer
│   │   ├── pages/             # JobsPage / NewJobPage / JobDetailPage
│   │   └── styles.css
│   ├── run_frontend.bat       # 一键启动前端
│   └── ...
├── docs/                      # 阶段间版本化接口文档
├── jobs/                      # 运行时数据；被 Git 忽略
└── README.md
```

---

## 三、启动方式

**后端**（终端 A）：

```bat
cd backend
run_backend.bat
```
首次运行会创建 `.venv` 并 `pip install -r requirements.txt`，然后监听 `http://127.0.0.1:8000`。

**前端**（终端 B）：

```bat
cd frontend
run_frontend.bat
```
首次运行 `npm install`，然后打开 `http://localhost:5173`。

`demo_room` 只需平台 Python 与 Node.js。真实 Oxford → MrHash-LiDAR 还要求服务器已注册数据、
可用的 MrHash/Pixi 环境以及算法所需的 ROS/CUDA 依赖；这些依赖始终与 FastAPI 环境隔离。

---

## 四、操作流程

### Mock demo

1. **新建任务**：进入首页 → “新建任务” → 选数据集 `demo_room` → 三个阶段各选一个算法
   （全部都是演示算法，任意组合均可）→ 创建。
2. **Run All**：任务详情页点击 **▶ Run All**，观察左侧三张卡片依次经历
   `等待 → 运行中 → 完成`；每张卡片实时显示 **阶段进度 / current+total / 耗时 / 日志流**。
3. **① 位姿轨迹**：Pose 完成后选中该阶段，右侧 3D 视角出现轨迹线（蓝）＋朝向短线（黄）＋
   起点/终点（绿/红），支持拖拽旋转、滚轮缩放、右键平移。
4. **② 表面网格**：Surface 完成后选中该阶段，出现 GLB 网格，查看器支持旋转/缩放/平移。
5. **③ 距离场**：Distance 完成后选中该阶段，有 XY / XZ / YZ 三个切面 Tab，每个切面可叠加
   三种图层：**距离场底图 / 可观测区域 / 梯度箭头**，页面底部 `±` 滑块调节切片索引。
6. **产物下载**：展开阶段右侧“产物与指标”面板。**只有 `download=true` 的产物可下载**
   （原始轨迹、切片压缩包）；仅预览类文件（网格、切面）只有预览入口。
7. **故障演示**：新建任务时选 `模拟失败阶段 = surface`，Run All 后 Surface 以
   “Simulated failure (demo)” 失败，后续 Distance 停在下游不再启动——展示失败隔离。
8. **取消 / 重跑**：任一阶段运行中点“取消”，状态走 `取消中 → 已取消`，下游不受影响；
   已取消 / 已失败阶段可点“↻ 重跑”。
9. **刷新恢复**：任务运行途中或完成后刷新浏览器，状态从磁盘完整恢复（任务、阶段、
   产物、日志全部在 `jobs/` 下）。

### Oxford → MrHash-LiDAR

1. 在新建任务页选择 `oxford_mrhash_lidar`。页面会限制组合为 Pose
   `registered_pose_import` 和 Surface `mrhash_lidar`；RGB-D Surface backend 不可选。
2. 创建 Job 后只点击一次 **Run All**。平台依次验证并导入已注册 Pose、生成
   `stage2_surface/input/surface_input_manifest.json`、再次校验输入并启动 MrHash-LiDAR。
3. `MAPPING_SURFACE_MODE=demo` 是真实短序列 smoke，帧上限由服务器环境变量
   `MRHASH_SMOKE_END_FRAME` 控制；`MAPPING_SURFACE_MODE=full` 使用完整可关联序列。
4. Surface 完成后，因真实 Distance backend 尚未接入，Run All 明确停在
   “Distance backend unavailable”；已完成的 Pose/Surface 不会被标记为失败。

---

## 五、安全模型（文件下载守则）

后端取文件走**唯一合法通道**：`/api/jobs/{job}/stages/{stage}/previews/{artifact_id}` 与
`.../artifacts/{artifact_id}`。每一步都在服务端校验：

1. 从该阶段的 `result_manifest.json` 中按 `artifact_id` 取 `path`；
2. 校验访问方式（`preview` role 才能走 preview 路由；下载必须显式 `download=true`，可支持
   `data` 或 `trajectory` 等已登记 role）；
3. 把解析后的绝对路径与作业/阶段目录比对，**不位于该目录内一律拒绝**（`../`、URL 编码、
   绝对路径等穿越尝试统一 404）。

前端不提交任何路径；展示用的服务器路径仅作说明。

---

## 六、数据 / 状态模型

```
jobs/<job_id>/
├── job.json                # 任务元数据 + 每个阶段的 backend/status/can_run 等
├── stage1_pose/progress.json      # 阶段运行中：phase / progress / current+total / message
├── stage1_pose/result_manifest.json  # 阶段完成：状态/耗时/指标/metrics/artifacts[]
├── stage1_pose/trajectory_preview.json # 预览文件（trajectory_model）
├── stage1_pose/poses.txt          # download=true 的导入 Pose 原件
├── stage2_surface/input/surface_input_manifest.json # Pose→Surface 标准输入
├── stage2_surface/result_manifest.json              # Surface 标准结果
├── stage2_surface/preview/surface_model.glb          # 浏览器简化预览
├── stage2_surface/runs/<run_id>/                     # 配置及完整 PLY；运行时数据
└── stage3_esdf/                   # Distance 阶段目录
```

- 阶段成功后**先写盘再发 SSE `stage.result`**，前端收到后 REST 全量刷新 → 浏览器刷新
  在任何时刻都能从磁盘恢复。
- SSE 连接断开由浏览器自动重连，重连后后端会补发全量 `snapshot` 帧。
- 状态机：`waiting → running → cancelling → cancelled` / `running → completed` /
  `running → failed`；下游阶段受上游完成状态门控。

---

## 七、真实算法接入契约

演示数据继续使用 Mock Runner。已注册的真实数据由后端调度器以**子进程方式**调用阶段脚本；
算法通过以下统一 CLI 契约接入：

```bash
backend/scripts/run_pose.sh    --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
backend/scripts/run_surface.sh --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
backend/scripts/run_esdf.sh    --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
```

脚本责任：

- **从标准输入/约定文件接收输入数据**（上一阶段的产物路径）；
- **写进度**：把 `{phase, progress, current, total, unit, message}` 写入实际阶段目录
  `stage1_pose/`、`stage2_surface/` 或 `stage3_esdf/`；
- **成功**：把产物写入对应实际阶段目录（`stage1_pose/`、`stage2_surface/`、
  `stage3_esdf/`），并在该目录的 `result_manifest.json` 中登记 `artifacts`（`artifact_id`、
   `role`、`content_type`、`download`，以及 metrics）；
- **退出码**：0=成功，非 0=失败（调度器把退出码写入状态并停止下游）；
- `--mode full` 时算法可加载自有环境（容器/Conda 等），但**后端代码本身不 import
   任何算法 Python 包**，算法环境与平台环境隔离。

`run_pose.sh` 已支持 `registered_pose_import`；`run_surface.sh` 当前唯一可运行的真实 backend 是
`mrhash_lidar`。`mrhash_rgbd` 仅注册用于接口校验并保持 disabled；`run_esdf.sh` 和其他尚未接入的
真实 backend 会明确拒绝运行。

### Oxford → MrHash-LiDAR

`oxford_mrhash_lidar` 是服务器端注册的真实数据集。浏览器只提交数据集 id；bag 和
`poses.txt` 的位置、大小及 SHA-256 由 `backend/config/datasets/` 控制。创建 Job
只建立服务器端符号链接，不复制大 bag，也不接受浏览器提供文件路径。

一次 Run All 会自动调用 `registered_pose_import`。它校验八列格式、严格递增时间戳、有限数值、
单位四元数及注册数据完整性，并写入
`stage1_pose/`。该 `poses.txt` 第一列是 MrHash Ros1Reader 使用的 ROS bag record
timestamp lookup key；后七列是按物理 LiDAR first-point 时间匹配原始 GLIM trajectory
得到的 `T_world_lidar`，两列时间不是同一时间基准。

Pose 完成后，调度器自动准备并验证 Surface 输入，再启动 MrHash。`demo` 模式在真实数据集上
表示真实小规模 smoke run，不是预制输出；`full` 使用全部可关联帧。
完整 PLY、voxel field、hash points 和本次配置保存在 Job 内；`surface_model` 是明确标注的
简化 GLB 预览。接口细节见 `docs/surface-input-manifest-v1.md`，Surface 到 Distance 的讨论草案
见 `docs/surface-to-distance-manifest-v0.md`。

### MrHash RGB-D 接口（provisional / Not Ready）

平台已注册 disabled 状态的 `mrhash_rgbd` backend。它的 backend 输入 modalities 为
`rgb / depth / camera_pose`，兼容层将其对应到 dataset modalities `rgb / depth / pose`。
该 backend 不允许用户选择或启动；注册此接口不代表真实 RGB-D 算法已经接通或验收。

目前已经准备并通过测试的内容包括：标准 Surface 输入 manifest、sequence index、规范化的
`T_world_camera` trajectory 语义、provisional `T_depth_rgb` 外参、depth scale 语义、artifact
size/SHA-256 与路径完整性校验、modality/backend compatibility，以及 validate-only adapter。

启用 backend 前仍需完成：

- 注册真实交接数据并完成字段映射；
- 按 sequence index 顺序将标准 trajectory JSON 转换为 MrHash 原生 `traj.txt`；
- 事务性生成 stage-local 的原生 `results/*.jpg`、`results/*.png` 和 `traj.txt` 布局，且不修改源文件；
- 由平台启动已确认的 `rgbd_runner.py` 入口；
- 根据实际输出识别并登记真实产物与预览；
- 完成真实 RGB-D smoke/full 验收后再启用 backend。

相关接口文档：

- [MrHash RGB-D 接口](docs/mrhash-rgbd-interface.md)
- [Surface Input Manifest v1](docs/surface-input-manifest-v1.md)
- [Surface → Distance Manifest v0 草案](docs/surface-to-distance-manifest-v0.md)

### 当前集成状态

| 能力 | 状态 |
|---|---|
| Registered Pose Import | 已实现并验证；验证并导入预计算 Pose，不运行 SLAM |
| Pose → Surface v1 | LiDAR confirmed；RGB-D 契约与校验为 provisional，待真实数据验收 |
| MrHash-LiDAR | 已接入；真实子进程 smoke/full verified |
| MrHash RGB-D interface | 已准备且测试通过；契约仍为 provisional |
| MrHash RGB-D runtime | 未接入；backend disabled / Not Ready，不可启动 |
| Real GLIM runner | 未接入；Oxford 当前使用 Registered Pose Import |
| H3-Mapping | 未接入 |
| Distance/ESDF | 未接入；当前只有 Surface → Distance v0 draft |
| 分布式服务器部署 | 未实施；阶段契约使用受控引用，不要求浏览器提供同机绝对路径 |

---

## 八、未实现清单

以下内容**未实现**，也不会伪装成已完成：

- 真实 GLIM Runner；Oxford 当前只导入并验证数据集注册的预计算 Pose；
- MrHash RGB-D runtime、H3-Mapping 及真实 ESDF/Distance runner；
- MrHash RGB-D 原生输入布局生成、runtime 启动、真实产物接入及真实数据 smoke/full 验收；
- 除已接入 MrHash 的 Pixi 子进程环境外，其他算法环境管理；
- 3D 体素场体渲染（当前是三个正交切面切片）；
- 任务持久化到数据库（当前为本地 JSON/文件，满足“刷新恢复”要求）；
- 多用户 / 登录鉴权 / 配额；
- 分布式调度（Redis/Celery/K8s）；
- 远程服务器（SSH/AutoDL）运行。

## 九、技术栈

| 层 | 选型 |
|---|---|
| 前端 | React 18 · TypeScript · Vite 5 · react-router |
| 3D | three.js · @react-three/fiber · @react-three/drei |
| 后端 | Python 3 · FastAPI · uvicorn |
| 存储 | 本地 JSON + 文件系统 |
| 实时 | Server-Sent Events（SSE） |
