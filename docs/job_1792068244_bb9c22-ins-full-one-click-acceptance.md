# 已验证 INS profile 完整 Pose → Surface 一键工程验收

新 Job：`job_1792068244_bb9c22`；结果：`completed`。使用自动化 Chromium 从正常 `/jobs/new` 页面选择已验证的 `ins_upload_64cf05888616`，选择“完整运行”，实际点击“创建并一键运行”。没有使用 HTTP 替代点击，也没有复用历史 Pose、Mesh 或成功状态。本次真实算法仅运行一次，无重试。

结论范围仅为已验证 INS profile 的完整两阶段一键流程。任意 bag 兼容与建图精度未验收；外参及 IMU 单位依据仍待确认；第三模块 Distance 未接入。

## 范围修复与入口

原问题：真实两阶段任务虽然以 `--mode full` 启动 Pose，但 Surface 仍读取数据集注册项中的 `integration_end_frame: 100`，所以网页“完整”入口可能只生成短段 Surface。

现在网页提供两个明确范围，默认完整运行：

| 选择 | Pose | Surface |
|---|---|---|
| 完整运行 | 新运行 GLIM，发布完整 LiDAR/IMU 序列 | 自动使用本 Job 新轨迹，整份 bag，end_frame=-1 |
| 短段验证 | 新运行完整 GLIM，沿用已验证策略 | 原始第 1–100 帧 |

API `POST /api/jobs` 接收 `run_mode=full|short`；服务端只对受控 INS GLIM/MrHash profile 接受此选择，并将选择与范围写入新 Job。Surface 准备阶段核对持久化 mode/scope 一致性后生成输入 manifest。完整模式覆盖新任务的帧范围，不修改原数据集注册项或任何已有 Job；未指定 run_mode 的旧调用保留旧语义。

本次创建响应中 Pose/Surface 都为 waiting、manifest 均为空；`run_mode=full`、`surface_end_frame=null`。实际 GLIM bridge 命令没有 max-lidar-frames/max-duration 截断，Surface input manifest 的 integration_end_frame 为 null，实际 MrHash 配置 start_frame=1、end_frame=-1。

Surface 的滤波、0.05 m 体素、0.40 m 截断距离、权重、深度范围、mesh 阈值等算法参数与完整 Surface 基线逐项一致。`n_frames_invalidate_voxels=100` 是原有算法参数，不是处理帧数截止；未修改。GLIM 配置、外参、IMU 加速度比例沿用受控 profile，关联门限保持 98%，时间容差保持 0.05 秒。另逐文件核对了与前 100 帧基线的 15 份有效 GLIM JSON 配置，字节全部一致。

## 实际执行、衔接与统计

| 指标 | 本次实际结果 |
|---|---:|
| 桥接实际发布 LiDAR | 1539 |
| 桥接实际发布 IMU | 30770 |
| GLIM 原生有效 Pose | 1527 |
| 标准 Pose / 关联数 | 1527 |
| 关联率 | 99.2203% |
| 关联门限 | 98% |
| Surface 全包 / 遍历 / 选中 | 1539 / 1539 / 1539 |
| Surface 关联 / 实际融合 | 1527 / 1527 |
| 无 Pose 跳过 | 12 |
| 范围外跳过 / 无效消息 / 空过滤结果 / compute 错误 | 0 / 0 / 0 / 0 |
| 内部漏帧 / 重复关联复用 | 0 / 0 |

1539 条 LiDAR 均发布并被 Surface 遍历。1527 条有效 Pose 对应原始第 12–1538 帧；跳过第 1–11 帧和第 1539 帧，位于轨迹初始化之前与末尾，均无可用 Pose，不放宽 lookup 容差强行填充。逐帧成功 compute ledger 与跳过记录互斥，完整覆盖 1–1539，无内部缺口、无重复融合。成功 compute 返回属于执行统计，不代表每帧精度已验证。

本次新 GLIM run_id：`glim_20261015_204806`。新 canonical poses.txt SHA-256：`1eebcd7714459e67cc3bebd5f8810f3955c19aa3be8b15bf1032fd1e857e8604`；新 native trajectory SHA-256：`aa900e11bb47a3664cb306985651c480be7826b498fdbc42f677610cdf962089`。canonical SHA 与两份历史基线不同。

新轨迹由本次 GLIM CUDA 进程和 ROS1→ROS2 bridge 生成，dump 收集至本 Job 的 stage1_pose/native/dump，未从旧 Job 导入。Surface trajectory reference 为本 Job 的 `stage1_pose/poses.txt`，其 SHA 与新 Pose manifest 一致；source_pose.run_id 指向上述新运行，origin=`GLIM runtime estimation`，pose_reuse=null。MrHash 本次 run_id 为 `20261015_204843_abe702ae`，raw 输出及配置均在本 Job 下；没有 package-existing-run，也没有历史 Mesh 输入。

页面仅触发一次创建与一次 run-planned 请求，没有单独点击 Surface 启动。SSE 记录顺序为 Pose completed → Surface input prepared（12 帧无 Pose 的计数警告）→ Surface completed → all completed；自动衔接由后端调度完成。

## GPU 排队与异常传播

本机只有一张 RTX 4090。网页创建前用独立进程持有同一个 gpu_pipeline.lock，仅用于队列测试、不启动算法。点击运行后，实际观察到 Pose queued，并保存页面截图与 API snapshot；释放锁后 GLIM 才启动。现有跨 Job 队列及排队取消测试也通过。

连续 401 次、约 1 秒间隔的进程树/GPU 采样先观察到 GLIM，再观察到 MrHash；两算法同时存在的采样数为 0。GPU 进程记录未出现其他算法工作负载，任一采样最多有 1 个 GPU compute 进程。一次退出过渡采样中 NVML 对已知 MrHash PID 返回 [No data]，该 PID 仍属于本 Job 进程树，已单独记录。本轮没有为验证排队启动第二个真实算法 Job。

异常传播通过隔离测试验证：Pose 失败或取消会停止下游；Surface 输入准备失败（含关联门限不满足）会将 Surface 和 Job 标记失败；Surface 执行失败会传播为 Job failed。真实本轮没有故意注入故障。首次扩展测试因旧测试夹具共用生产 GPU 锁而出现超时，已把测试锁改为临时目录隔离后重测通过；真实 Job 没有因此重跑或被修改。

## 耗时与资源

- Pose 阶段：241.5 秒。
- Surface 阶段：198.4 秒；其中 reader/融合循环 123.815 秒、GLB 封装 28.77 秒。
- 创建至全部完成约 459 秒；包括队列等待、两阶段之间约 18 秒的输入准备校验。两阶段耗时均含各自启动/结束开销。
- 采样 GPU 显存峰值 20642 MiB，GPU 利用率峰值 33%。
- 进程树 RSS 合计峰值 12618724 KiB，约 12.03 GiB；可能重复计入共享页。GPU 指标是设备级，1 秒采样不能代表毫秒级瞬时峰值。

## 产物、网页与持久化

| 产物 | 本次结果 |
|---|---:|
| 原生 Mesh 顶点 / 面 | 3170312 / 2389022 |
| 原生 voxel / hash 点 | 9610325 / 41355 |
| GLB 预览顶点 / 面 | 276980 / 500000 |
| GLB 简化前 / 后面数 | 2389022 / 500000 |
| GLB 大小 | 12648752 字节 |

GLB 按既定 500000 面阈值执行精确坐标去重与 QEM，SHA-256 `d3e21bb54090e5f357fed726a9e99d587b5e1c67ba0e004a6dbe5d0c49ef8db2`。manifest 自动登记封装方法、简化标记、前后面数、bounds、大小和 SHA；网页明确显示原生 2389022 面 → GLB 500000 面，说明预览可改变小分量与边界，完整原生 Mesh 可下载。

GLB 无黑色 COLOR_0，沿用中性灰 PBR。Pose 预览、Mesh 的灰色/法线/原始材质模式、重置视角、刷新与范围说明均通过自动化浏览器检查，页面无 JavaScript 异常。原生 Mesh、voxel、hash 完整保留，没有新增删碎片、补洞或平滑。GLB 仍有 844 个零法线顶点；局部几何和法线问题保留为质量诊断项，未将工程链路成功解释为精度通过。

Pose 的 7 个 artifact、Surface 的 7 个 artifact 均经真实预览/下载接口获取，HTTP 200，下载 SHA 与本地一致；已声明的文件 SHA/大小及预览 SHA 与元数据一致。服务重启后，completed 状态、阶段结束时间、run_mode、范围、产物及第三模块 not_integrated 状态均保留；14 个 artifact 再次下载验证通过。

部署脚本新增 HTTP 就绪检查：进程存在后等待 backend /api/health 与 frontend / 返回成功，避免 Vite 尚未监听就立即检查导致连接拒绝。最新部署与持久化检查通过。

必要测试最终通过：范围/创建/队列/异常/输入相关 47 项，GLIM/桥接/时间关联/进程清理/预览相关 72 项，共 119 项；前端 TypeScript/Vite 构建与部署脚本 bash 语法检查通过。

基线 `job_1792052071_70692b` 的 93 个普通文件、`job_1792067103_dab12b` 的 106 个普通文件，在本次运行前后文件集合与 SHA 全部一致，包括原有配置、结果、预览及验证记录。未提交或推送 Git。

## 访问与剩余边界

服务器本机：`http://127.0.0.1:5173/jobs/job_1792068244_bb9c22`；新建入口 `http://127.0.0.1:5173/jobs/new`。从个人电脑访问时，通过现有 SSH/端口转发将服务器 127.0.0.1:5173 映射到本机 5173 即可；前端已代理 /api，无需单独转发 8000。服务仍只监听服务器回环地址。

已完成自动化浏览器真实点击验收，本轮没有保留“只能 HTTP、人工点击待验收”项。可按同一入口人工复核。

剩余边界：仅验证这份受控 INS bag/profile；外参和 IMU 单位依据待确认；建图精度、任意 bag 兼容、ESDF/Distance 均未验收。Pose 流式阶段目前显示日志与阶段状态，没有可靠的逐帧百分比；最终计数来自 bridge 完成日志及 association。GLB 简化和局部零法线属于明确保留的显示/几何限制。Vite 原有大 chunk 提示仍存在。测试浏览器缺少中文字库，截图中文可呈方框；DOM 文本与交互检查通过。

## 证据

本 Job 的 `verification/` 包含 create_request/response、browser_creation_checks、queue_snapshot、pose_queued 截图、pipeline_resource_samples/summary、sse_events、engineering_audit、download_checks_before_restart、persistence_checks、browser_result_checks、两组测试日志及结果截图。

真实算法日志：`stage1_pose/run.log`、`stage1_pose/native/run.log`、`stage2_surface/run.log`。逐帧融合记录和 accounting 在 `stage2_surface/runs/20261015_204843_abe702ae/raw/`。
