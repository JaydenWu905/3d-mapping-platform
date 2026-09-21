# 三模块三维建图系统 — Phase 1（演示与调度框架）

三维建图平台：**位姿估计（Pose/SLAM）→ 稠密建面（Surface）→ 距离场（ESDF）** 三阶段流水线的
**网页展示 + 轻量调度** 框架。

> **Phase 1 定位（诚实说明）**：本阶段**不包含任何真实建图算法**，也不依赖
> GLIM / MrHash / H3 / ROS / Conda / CUDA。所有阶段由 **伪 Runner** 按预设节奏产出一条
> 完整的数据链路（轨迹 → GLB 网格 → ESDF 切片），用于：
> 1. 验证三阶段调度、实时状态、失败/取消/重跑的整体流程；
> 2. 验证三套 3D 前端查看器（轨迹 / 网格 / 距离场切片）；
> 3. 作为 Phase 2 真实算法接入的“插座”（见下方 *Phase 2 接入契约*）。
>
> 未实现的真实算法部分（见 *未实现清单*）**没有**被描述为已完成。

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
│  │ 调度器            │  │ Mock Runner（Phase 1）           │  │
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
│   │   └── services/          # 调度器、Mock Runner、磁盘状态
│   ├── scripts/               # Phase 2 适配器脚本（约定，见下）
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
├── jobs/                      # 运行时数据（job.json / progress.json / manifest / 预览文件）
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

> 无 Conda / Pixi / ROS / CUDA；只需 Python 3.10+ 与 Node.js 18+。

---

## 四、演示流程（Demo Walkthrough）

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

---

## 五、安全模型（文件下载守则）

后端取文件走**唯一合法通道**：`/api/jobs/{job}/stages/{stage}/previews/{artifact_id}` 与
`.../artifacts/{artifact_id}`。每一步都在服务端校验：

1. 从该阶段的 `result_manifest.json` 中按 `artifact_id` 取 `path`；
2. 校验产物角色（`preview` 走 preview 路由，`data` 且 `download=true` 才走 artifact 路由）；
3. 把解析后的绝对路径与作业/阶段目录比对，**不位于该目录内一律拒绝**（`../`、URL 编码、
   绝对路径等穿越尝试统一 404）。

前端不提交任何路径；展示用的服务器路径仅作说明。

---

## 六、数据 / 状态模型

```
jobs/<job_id>/
├── job.json                # 任务元数据 + 每个阶段的 backend/status/can_run 等
├── pose/progress.json      # 阶段运行中：phase / progress / current+total / message
├── pose/result_manifest.json  # 阶段完成：状态/耗时/指标/metrics/artifacts[]
├── pose/preview/*.{json,glb,png}   # 预览文件（trajectory_model 等）
├── pose/data/trajectory_raw.json   # download=true 的原始数据
└── ...（surface/、distance/ 同上）
```

- 阶段成功后**先写盘再发 SSE `stage.result`**，前端收到后 REST 全量刷新 → 浏览器刷新
  在任何时刻都能从磁盘恢复。
- SSE 连接断开由浏览器自动重连，重连后后端会补发全量 `snapshot` 帧。
- 状态机：`waiting → running → cancelling → cancelled` / `running → completed` /
  `running → failed`；下游阶段受上游完成状态门控。

---

## 七、Phase 2 接入契约（真实算法替换点）

Phase 1 的 Mock Runner 是唯一需要替换的部分。后端调度器以**子进程方式**调用各阶段脚本，
真实算法通过实现以下统一 CLI 契约接入，**前端与调度代码一行都不用改**：

```bash
backend/scripts/run_pose.sh    --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
backend/scripts/run_surface.sh --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
backend/scripts/run_esdf.sh    --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
```

脚本责任：

- **从标准输入/约定文件接收输入数据**（上一阶段的产物路径）；
- **写进度**：把 `{phase, progress, current, total, unit, message}` 写入
  `<job_dir>/<stage>/progress.json`；
- **成功**：把产物按约定写入 `<job_dir>/<stage>/preview|data/`，并在
  `<job_dir>/<stage>/result_manifest.json` 中登记 `artifacts`（`artifact_id`、
   `role: preview|data`、`content_type`、`download`，以及 metrics）；
- **退出码**：0=成功，非 0=失败（调度器把退出码写入状态并停止下游）；
- `--mode full` 时算法可加载自有环境（容器/Conda 等），但**后端代码本身不 import
   任何算法 Python 包**，算法环境与平台环境隔离。

`backend/scripts/` 下已放置 `run_{pose,surface,esdf}.sh` 三个骨架脚本。
**Phase 1 中后端并不调用它们**（当前由内置 MockRunner 演示）；骨架脚本如果被直接执行会
立即以非 0 退出并打印“尚未接入”，以明确标记该链路未实现。

---

## 八、未实现清单（Phase 1 明确范围外）

以下内容**未实现**，也不会伪装成已完成：

- 真实 SLAM / 建面 / ESDF 算法（GLIM、fast_livo2、lio_sam、mrhash_lidar、
  mrhash_rgbd、h3_rgbd、voxel_esdf、kernel_sdf、oren 均未安装、未调用）；
- ROS / 传感器数据接入 / 相机内参、外参处理；
- Conda / Pixi 环境管理与算法环境隔离（Phase 2 统一由适配器脚本负责）；
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