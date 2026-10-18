# 预览等待区“扫描小车”验收记录

- 分支：`feat/waiting-preview-scanner`
- 基线：远端 `main` `b2e74cf6bf6bf3b480ab06095bbb93e20e9c8e10`（本地 `HEAD` 与之相同，改动尚未提交）
- 范围：仅前端等待区接入扫描小车示意；未改动后端、HTTP 接口、任务调度、算法适配器、数据协议，未升级 React / Router / Vite / MUI / Three。

## 实现范围

- 新增独立组件 `frontend/src/components/WaitingPreview.tsx`，只接收现有 `StageDetail` 与 `useJob` 的 `connected`，不新增后端字段、不写回任何状态。
- 绘制与状态拆分为纯 TypeScript 模块：
  - `frontend/src/components/waitingPreview/state.ts`：由阶段状态、阶段进度、GLIM 输入发布进度、连接状态派生模式、展开量、文案。
  - `frontend/src/components/waitingPreview/route.ts`：固定的 17×11 示意房间、三条蛇形扫描路线、累计长度与 `routeAt`。
  - `frontend/src/components/waitingPreview/draw.ts`：Canvas 2D 绘制（方格地砖、障碍、虚线完整路线、进度裁剪的已展开路线、小车、扫描扇区）。
  - `frontend/src/components/waitingPreview/artifacts.ts`：判断当前阶段是否存在真正可用的预览产物。
- `frontend/src/pages/JobDetailPage.tsx` 的 `StageViewer` 在“阶段仍在等待/处理、但尚无可用产物”时渲染 `WaitingPreview`；产物判定沿用既有映射：
  - 位姿：`trajectory_model`
  - 表面：`surface_model`
  - 距离场：`slice_xy` / `slice_xz` / `slice_yz`
  - 有真实产物时仍优先原有 `TrajectoryViewer` / `MeshViewer` / `EsdfViewer`，真实查看器的加载与错误反馈保持原样；不以 `progress < 100` 判断接管。
- `frontend/src/styles.css` 增加等待区样式：与真实预览同高、方形边框、主题变量取色、展示模式放大、窄屏 360px 并纵向堆叠。
- `frontend/src/components/StageCard.tsx` 仅为阶段卡补充 `data-stage-key` 与 `aria-current`，便于定位与无障碍，无行为变化。
- 新增 `frontend/tests/waitingPreview.test.cjs`。

## 进度耦合约定

- 复用 `progressLabel.ts` 的 `progressBarState(stage)`：`percent` 为 `null` 时不伪造百分比，展开量为 0。
- 位姿阶段在 GLIM `input_publishing` 时使用输入发布进度；`waiting_glim_export` / `associating` 或输入已到 100% 时，只把路线完全展开并让小车待命，文案为“输入已发布，等待轨迹导出/关联”，不显示“位姿估计完成”。
- 阶段进度 100% 但状态仍为 `running` 时继续等待，不显示完成。
- 展开量只由服务端有效进度决定；动画只影响小车巡逻、扫描扇区与扫描点。固定进度下画布随快照变化而不是随时间增长，进度回退时展开量同步回退。
- 断线时保留最后一次有效画面并暂停装饰动画，显示“连接中断，正在重连”；恢复后按新快照继续。
- 点击画面、换个方向、换个房间只改变本地示意图，不发起任何请求；浏览器验收中记录到的变更型 API 请求为 0。
- 等待区恒定显示“等待互动 · 非实时地图”，底部说明“展开量跟随进度；图形为示意，不是真实地图。”

## 状态文案

| 情况 | 模式 | 场景 | 说明 |
| --- | --- | --- | --- |
| 运行中，有效进度 | `running` | 显示 | 路线按进度展开，可暂停 |
| 运行中，无有效进度 | `running` | 显示 | “进度未上报”，零展开 |
| GLIM 输入发布完毕 / 等待导出 / 关联中 | `running` + 待命 | 显示 | 只待命，不宣称完成 |
| 排队 | `queued` | 隐藏 | “排队中” |
| 尚未开始 | `not-started` | 隐藏 | “尚未开始” |
| 取消中 | `cancelling` | 显示静态 | 保留最后展开量，隐藏互动按钮 |
| 已取消 | `cancelled` | 隐藏 | 停止动画 |
| 失败 | `failed` | 隐藏 | 停止动画 |
| 完成但无可用产物 | `completed-missing` | 隐藏 | 显示异常提示，不当作完成 |
| 未请求该阶段 | `not-requested` | 隐藏 | “未请求该阶段” |
| 连接中断 | 保留原模式 | 静态 | 保留最后画面并提示重连 |

## 静态检查

以下命令均在 `frontend` 目录执行：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 类型检查 | `npm.cmd run typecheck` | 通过 |
| 生产构建 | `npm.cmd run build` | 通过；保留既有 chunk >500 kB 提示 |
| 等待区状态与生命周期 | `node tests/waitingPreview.test.cjs` | 通过 |
| 位姿进度语义 | `node tests/poseProgress.test.cjs` | 通过 |
| 任务展示语义 | `node tests/jobDisplay.test.cjs` | 通过 |
| 观测进度采样 | `node tests/progressHistory.test.cjs` | 通过 |

`waitingPreview.test.cjs` 覆盖：三阶段 0% / 20% / 50% / 80% / 100% 差异、位姿输入发布进度、同快照重复推导一致、进度回退、越界与 `NaN`、输入 100% 与 `waiting_glim_export` / `associating` 待命、阶段 100% 仍等待、排队 / 未开始 / 未请求、失败 / 取消 / 取消中 / 完成缺产物、断线与恢复、真实产物接管判据、示意路线与展开格数、房间布局稳定、紧凑高度布局，以及组件源码约束（单一 RAF、30fps、DPR 上限 2、ResizeObserver、`visibilitychange` 清理、无定时器、无网络请求、展开量取 `snapshot.state.reveal`、页面接管判据）。

## 浏览器验收

### 真实后端（本机 FastAPI + Vite dev server）

真实任务 `job_1792299522_8a53b0`，后端组合 `registered_pose_import` / `mrhash_lidar` / `voxel_esdf`，通过 `POST /api/jobs` 创建后 `run-all`：

- 位姿、表面、距离场三个等待态均出现扫描小车，等待态可暂停、换房间、换方向。
- 距离场等待态：`reveal=0.2062`、`percent=20.62`、`animating=true`、`scene=true`。
- 真实产物接管后等待区消失：距离场 `waiting=0`、`viewer=1`。
- 连续切换阶段 20 次后：`waiting=0`、`viewer3d=1`、`esdf=0`、`canvas=1`，未累积画布或视图。
- 截图：`01-pose-waiting-1920.png` … `08-distance-real-takeover-1920.png`；数据：`real-run-2.json`。

说明：本机真实后端使用仓库自带的 mock 运行器，无法产生 GLIM `input_publishing` / `waiting_glim_export` / `associating` 阶段，也无法注入断线或指定终态。因此下面这些场景使用独立的 fixture HTTP/SSE 服务验证；该服务只模拟状态与快照，不参与真实算法计算。

### Fixture 服务（状态 / 断线 / 响应式）

同一套前端组件，后端为 fixture：

| 场景 | 结果 |
| --- | --- |
| 输入发布 100%，等待轨迹导出 | `mode=running`、`percent=100.00`、`reveal=1`、待命文案正确、无“位姿估计完成”、无真实查看器 |
| 断线 | 标题“连接中断，正在重连”，动画停止，展开量保持 1，前后两帧画布完全一致 |
| 恢复 | 动画恢复，展开量保持 1 |
| 进度 20% → 80% → 30% | 展开量 0.2 → 0.8 → 0.3，回退同步收回；固定 20% 等待 1.4s 不增长 |
| 手动暂停 | 动画停止，两帧一致，可继续 |
| 点击 / 换方向 / 换房间 | 展开量与百分比不变，变更型 API 请求 0 条 |
| 排队 / 未知进度 / 完成缺产物 / 失败 / 取消中 / 已取消 / 关联中 | 模式、动画、文案逐项断言通过 |
| 1366×768 | 等待区 739.8×458，页面横向溢出 0，按钮全部在内且无重叠 |
| 390×844 | 等待区 340×360，横向溢出 0，按钮全部在内且无重叠 |
| 展示模式 | 高度 760 → 830，横向溢出 0，按钮在内 |
| 20 次阶段切换 | 等待区 1、`viewer-3d` 0、ESDF 0、canvas 1 |
| 资源计数 | Documents 1、Nodes 2410、JSEventListeners 409、JSHeapUsedSize 21.9 MB |
| 减少动态效果 | 动画关闭，显示“静态显示”，700ms 内两帧一致；快照 20% → 60% 时静态帧重绘且展开量更新 |

截图：`09-waiting-export-1920.png` … `24-reduced-motion-1920.png`；数据：`fixture-run.json`。

### 已知告警

- 控制台仅有 1 条 `404 (Not Found)`（静态资源），fixture 服务记录的失败响应为 0。
- 真实任务页面存在既有的 React 重复 key 告警，来自 `ArtifactsPanel.tsx` 以数值作为 `key` 的指标项，与本次改动无关，未修改。
- 本次验收环境无法直接查看截图内容，布局与文案由 DOM 属性、几何边界和截图文件共同验证。

## 截图索引

- `01-pose-waiting-1920.png`：位姿等待，蓝色路线按进度展开
- `02-pose-real-takeover-1920.png`：真实轨迹接管
- `03-surface-waiting-1920.png`：表面等待，紫色三角网格
- `04-surface-room-changed-1920.png`：切换示意房间
- `05-surface-paused-1920.png`：手动暂停
- `06-surface-real-takeover-1920.png`：真实表面模型接管
- `07-distance-waiting-1920.png`：距离场等待，青色距离色块
- `08-distance-real-takeover-1920.png`：真实 ESDF 接管
- `09-waiting-export-1920.png`：输入发布 100%，等待轨迹导出
- `10-disconnect-1920.png` / `11-reconnect-1920.png`：断线与恢复
- `12-progress-80-1920.png` / `13-progress-fallback-30-1920.png`：进度前进与回退
- `14-paused-static-1920.png`：暂停静态帧
- `15-queued-1920.png`、`16-unknown-1920.png`、`17-completed-missing-1920.png`、`18-failed-1920.png`、`19-cancelling-1920.png`、`20-cancelled-1920.png`、`21-associating-1920.png`：各状态
- `20-responsive-1366x768.png`、`21-responsive-390.png`：响应式
- `22-display-mode-1920.png`：展示模式
- `23-cycle20-1920.png`：20 次阶段切换后
- `24-reduced-motion-1920.png`：减少动态效果
- `real-run-2.json`、`fixture-run.json`：自动断言数据

## 已知限制

- GLIM 输入发布与等待导出阶段、断线、指定终态只能由 fixture 服务构造；真实算法环境的上述分支未在本机执行。
- 距离场示意中的色块只表示示意路线上的相对空旷程度，不是真实米制距离，界面已明确标注。
- 等待区为 Canvas 2D 示意，不加载点云或网格，不替代真实结果。
