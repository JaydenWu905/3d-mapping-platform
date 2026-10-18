# 任务联动小车动画与已有成果切换：实施验收

日期：2026-10-18。对应 [实施计划](../../docs/task-linked-waiting-preview-plan-20261018.md)。本报告记录本轮已完成的实现和实际验收，计划文档末尾的“只新增计划”属于实施前记录。

## 使用入口

- [新建并运行演示任务](http://127.0.0.1:5173/jobs/new)：选择 `demo_room`，点击“创建并一键运行”，后台串行执行三阶段。
- [已验收的完整任务](http://127.0.0.1:5173/jobs/job_1792306497_d631cf)：`job_1792306497_d631cf`，三阶段均已完成，可查看三种成果。
- 原 `/demo/waiting-preview` 地址重定向到正常新建任务入口，主导航没有独立纯动画入口。

表面重建期间，可切换“已有成果 → 位姿估计”；距离场期间，可查看位姿和表面网格。顶部的后台执行提示始终更新。查看已有成果不会停止任务，新阶段或新成果到达也不会抢走用户选定的成果。

小车没有场景交互按钮。新运行自动更换房间及方向；同次运行在动画和成果之间切换时保持场景。路线、网格、距离色块的展开量来自任务进度，没有前端进度计时器。

## 完整任务证据

最终完整浏览器验收从正常新建页面操作，使用运行中的 FastAPI、实际 REST/SSE、磁盘任务文件及预制演示资源；没有通过拦截响应、前端时间线或 fixture 伪造任务完成。

| 阶段 | 最终状态 | 清单记录耗时 | 已验证的产物 |
| --- | --- | --- | --- |
| 位姿估计 | completed | 30.45 秒 | `trajectory_model` 实际加载，另有可下载轨迹 |
| 表面重建 | completed | 30.18 秒 | `surface_model` GLB 实际加载并显示 |
| 距离场 | completed | 30.54 秒 | `slice_xy/xz/yz` PNG 实际加载 |

三阶段清单、进度、预览 HTTP 200 记录及最终任务快照保存在 [browser-results.json](browser-results.json)。所有清单均明确包含 `mock_backend: true` 和演示来源说明。刷新后状态和成果仍可恢复。

这证明的是实际任务系统驱动的 **mock 演示链**。演示成果是预制合成数据，没有据此宣称真实 GLIM/MrHash、CUDA 或测试机 GPU 算法验收通过。

## 验证结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 前端类型检查、生产构建 | 通过 | [frontend-results.json](frontend-results.json) |
| 前端五组状态与回归测试 | 全部通过 | `taskPreview`、`waitingPreview`、`poseProgress`、`jobDisplay`、`progressHistory` |
| Linux 后端相关回归 | 97/97，无失败、错误或跳过 | [backend-results.json](backend-results.json) |
| 完整真实 HTTP/SSE 浏览器流程 | 9/9 | [browser-results.json](browser-results.json) |
| 资源回收、断线、失败、取消、旧入口 | 5/5 | [lifecycle-results.json](lifecycle-results.json) |
| 独立反复切换及下游失效复测 | 通过 | [switch-probe.json](switch-probe.json) |
| 缺少法线的 GLB 灰色/法线显示 | 目视通过 | 截图 06、15、16 |

20 次模式切换后：一个活动画布、一条事件连接、切换引起的变更型请求为 0。等待动画的活动 RAF 为 1，查看成果时等待动画 RAF 为 0。表面重试保留位姿成果，同时移除旧距离场清单；位姿重跑使表面和距离场成果失效。

断线验收使用测试专用透明 HTTP 代理，原样转发真实后端 SSE，然后销毁该测试页面对应的 TCP 流。动画画布在断线期间逐字节保持静止，RAF 为 0；自动重连后从 22.34% 更新到后台的 31.67%，恢复为一个连接。没有停止后端、合成进度帧或注入浏览器错误事件。代理已关闭。

失败/取消验收任务为 `job_1792306327_e1f93f`，通过原有 `fail_stage` 演示选项创建。表面失败及重试取消后，位姿成果仍可实际加载，失败/取消提示保持可见。截图 11–14 来自这组独立生命周期验收及资源复测任务，不与完整成功任务混为一轮。

1920×1080、1366×768、390 宽、手机展示模式均已截图检查；1366、390 和展示模式的页面宽度与工具栏溢出断言通过。减少动态效果时停止连续动画，仍随真实进度静态重绘。

## 实现范围

- `runner_service.py` 依服务端数据集 `execution` 区分 mock 与真实表面输入准备，覆盖单独启动、串行启动及重试路径；真实位姿语义校验保持有效，缺字段仍拒绝启动。
- `mock_runner.py` 默认每阶段约 30 秒，使用单调时钟安排进度写盘和原有事件；服务端可用 `MAPPING_MOCK_STAGE_DURATION_SEC` 调整，仅作用于 mock。配置必须是有限正数且不超过 3600 秒，自动化测试用短时长。
- 上游重跑移除失效的下游清单并重置状态，复用已有 `stage.result` 通知页面重新读取。
- 任务页分离后台执行阶段、预览模式及成果选择，复用原有三个查看器和一条 `useJob` 事件连接；切换只改变本地视图。
- 小车自动场景保存在有界会话记录中，无暂停、点击目标、换房间或换方向功能。恢复尺寸观察器，保留隐藏页面、减少动态效果及断线的停止处理。
- 示例 GLB 没有 `NORMAL` 属性；替换显示材质时沿用 GLTFLoader 的面法线处理，修复灰色及法线模式变黑的问题，不修改源网格。
- `frontend/src/api/api.ts`、`backend/app/api/`、`backend/app/models/` 无改动；没有改 HTTP 路由、请求或响应模型、真实算法参数、设备配置，也没有升级依赖。

## 截图索引

| 截图 | 内容 |
| --- | --- |
| [01](01-pose-task-animation.png) / [02](02-surface-task-animation.png) | 位姿 / 表面小车及后台进度 |
| [03](03-pose-result-during-surface.png) | 表面运行时查看实际位姿 |
| [04](04-after-20-switches.png) | 20 次切换后返回动画 |
| [05](05-pinned-pose-during-distance.png) | 后台进入距离场，位姿视图仍保持 |
| [06](06-mesh-during-distance.png) / [07](07-distance-task-animation.png) | 距离场运行时查看网格 / 切回小车 |
| [08 桌面](08-layout-1366.png) / [08 手机](08-layout-390.png) / [09](09-display-mode-mobile.png) | 窄屏与展示模式 |
| [10](10-completed-distance-result.png) | 三阶段完成，实际距离场切片 |
| [11](11-real-network-recovered.png) / [14](14-sse-disconnected-frozen.png) | SSE 重连 / 断线冻结 |
| [12](12-surface-failed-pose-still-viewable.png) / [13](13-surface-cancelled-pose-still-viewable.png) | 失败 / 取消后查看前序位姿 |
| [15](15-mesh-gray-confirmation.png) / [16](16-mesh-normal-confirmation.png) | 缺少法线的示例网格，灰色 / 法线模式；独立复测使用任务 `job_1792305870_690d07` |

## 回归与本机运行

前端在 `frontend/` 下执行：

```powershell
npm.cmd run typecheck
npm.cmd run build
node tests/taskPreview.test.cjs
node tests/waitingPreview.test.cjs
node tests/poseProgress.test.cjs
node tests/jobDisplay.test.cjs
node tests/progressHistory.test.cjs
```

后端在 Linux 的 `backend/` 目录执行以下八个模块，共 97 个测试：

```sh
python -m unittest tests.test_demo_task_chain tests.test_ins_run_modes tests.test_surface_input tests.test_rgbd_surface_input tests.test_pose_timestamp_service tests.test_jobs_api_errors tests.test_glim_dataset_and_dispatch tests.test_dataset_backend_compatibility
```

本机后端使用 Ubuntu-22.04 WSL 与 `/tmp/3d-mapping-platform-preview-venv/bin/python`，监听 `127.0.0.1:8000`；前端监听 `127.0.0.1:5173` 并代理现有 API。没有为 Windows 原生环境伪造 `fcntl`。后续重启时需保留现有依赖环境并从本仓库启动。

已知既有提示：构建的 chunk 超过 500 kB；浏览器有静态资源 404、React Router future 提示和 `ArtifactsPanel` 的重复 key 告警。完整流程没有未捕获页面错误。本次未扩展修改这些无关问题。

本轮只作本地提交，不推送、不部署。使用已配置的真人 Git 身份，不添加额外共同作者。`reports/handheld-slam-research-20261009/` 和既有 `reports/waiting-preview-auto-20261018/` 保留在工作区，不纳入本轮提交。
