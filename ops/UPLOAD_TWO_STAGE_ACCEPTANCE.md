> 后续更新：已通过自动化浏览器真实点击完成已验证 INS profile 的完整 Pose→Surface 一键工程验收，见 [新报告](../docs/job_1792068244_bb9c22-ins-full-one-click-acceptance.md)。下文记录的是早期 HTTP/短段验收现场，其中“人工点击待验收”已由本次验收覆盖。

# INS/Livox 上传与两阶段一键运行验收

## 范围与结论

本轮固化 GLIM Pose → 标准时间戳关联 → 同 Job Surface 输入 → MrHash-LiDAR → 原生产物及 GLB 封装。真实 Job 只声明 Pose、Surface；Distance 显示“未接入”，不执行。`demo_room` 的三阶段 Run All 保留。工程验收模式使用完整 Pose 与原始 LiDAR 第 1–100 帧 Surface，98% 关联门限、最大 0.05 秒及无重复使用约束保持。此范围不能代表完整场景重建和精度验收。

**新上传数据集**：`ins_upload_64cf05888616`，上传会话 `up_27ade933d5cb4e029c908854c0e47370`。

**新 Job**：`job_1792052071_70692b`，自动运行后状态 `completed`；Pose、Surface 均为 `completed`，Distance 为 `not_integrated`。基线 `job_1792049139_57c00d` 及其产物未覆盖。服务重启后两个 Job 仍显示两阶段 `completed`；真实 Job 的 `run-all` 返回 HTTP 409，避免启动第三模块。

## 上传、预检与注册

本版唯一 profile：`ins_livox_mid360_verified_bag`，仅接受已验证的 ROS1 原始 INS `.bag`，17,125,894,059 字节，SHA-256 `b7a0e7b20e8f447ff6f49be9470b812ded678e28d96f943f7f9b97fd40250c7f`。此约束阻止其他 Livox bag 自动继承 INS 外参与 IMU 加速度单位。上传由服务端生成会话 ID、数据副本目录和 dataset JSON；客户端只传文件字节、受控 profile、分块 offset 与每块 SHA-256。每块最多 64 MiB，流式写盘，写入后 fsync 并原子提交 offset。断线可查询 offset 续传；未完成、整文件 SHA 不符或预检失败的会话不能注册。注册 JSON 最后原子发布。

HTTP 上传会话记录：`runtime/acceptance_upload_session.json`、`runtime/acceptance_upload.log`、`runtime/acceptance_upload_resume.log`、`runtime/acceptance_finalize.json`。原始 bag 保持在 `/root/autodl-tmp/INS/2024-06-04-16-24-55.bag`；新副本位于 `uploads/datasets/ins_upload_64cf05888616/source.bag`。新注册数据集为 `backend/config/datasets/ins_upload_64cf05888616.json`。自动预检确认 ROS1 bag v2、`/livox_mid360/livox/lidar` 的 `livox_ros_driver2/msg/CustomMsg` 1539 条和 `/livox_mid360/livox/imu` 的 `sensor_msgs/msg/Imu` 30770 条；各解码抽检 3 条，检查点数、xyz、reflectivity、offset_time、时间戳及 IMU 加速度字段。

首轮完成上传时，整文件 SHA 已通过，但 rosbags 不识别暂存文件 `.bag.part` 扩展名，预检返回 422，未注册。修复为同一 inode 的临时 `.bag` 硬链接后，在同一上传会话重新执行 finalize，HTTP 200 并自动注册；没有重传或复制第二份 17 GB 数据。

## 自动运行结果

`POST /api/jobs` 创建上述新 Job，`POST /api/jobs/job_1792052071_70692b/run-planned` 一次触发自动执行完整 GLIM、轨迹关联、同 Job Surface 输入准备、MrHash 融合和 GLB 封装。完整命令见 `runtime/acceptance_command_history.txt`。GLIM 无界面 GPU 节点退出码 0，桥接发布 **1539 条 LiDAR、30770 条 IMU**；原生 sensor 时间轨迹 1527 行，标准 bag record 时间 Pose 1527 行，`bag_index.tsv` 1539 行。首尾时间如下：

| 时间项 | 首 | 尾 |
| --- | --- | --- |
| 原生 sensor 秒 | 1717493096.801825 | 1717493249.4020455 |
| 标准 Pose record 秒 | 1717493096.9027765 | 1717493249.5026836 |
| bag_index record 纳秒 | 1717493095803061748 | 1717493249602701942 |
| bag_index sensor 纳秒 | 1717493095701965809 | 1717493249502075434 |

关联 1527/1539，**99.2203%**，超过原 98% 门限；最大最近邻残差 0 ns、重复使用 0、逆序 0，头部缺 11、尾部缺 1、内部缺 0。全部 Pose 值有限、时间严格递增、四元数范数有效。`stage1_pose/native/association.json` 与新配置副本、桥接/节点日志、原生 dump 和标准轨迹均保存在本 Job；Surface handoff 通过。

Surface 使用 `mrhash_profile=ins_livox_mid360_custom`，配置中的 `start_frame=1,end_frame=100` 为原始 LiDAR topic 的 **1 起始、两端包含** 范围。选中 **100**、成功关联 **89**、因 GLIM 初始化没有 Pose 而跳过 **11**、实际融合 **89**；没有历史位姿、固定时间偏移或无效位姿兜底。`stage2_surface/runs/20261015_161923_420cdb10/raw/frame_accounting.json` 及算法日志保存逐帧计数。`packaging_resumed_from_raw_run=false`，本次由正常运行路径自动封装，无人工 package-only 重做。

新原生 mesh **249,413 顶点、199,873 面**，包围盒 `[-1.925,-11.6729,-0.825]` 至 `[26.9224,4.12574,3.88144]` 米；voxel **1,034,493 点**，hash **6,614 点**；GLB 预览 **109,981 顶点、199,873 面**。mesh、voxel/hash 的 xyz、sdf、weight 及 GLB 几何均为有限值，检查结果在 `jobs/job_1792052071_70692b/geometry_checks.json`。GLB、mesh、voxel、hash、配置、逐帧统计与全部 Pose 产物通过平台预览/下载 API 检查，**13/13 HTTP 200 且非空**，字节数见 `jobs/job_1792052071_70692b/api_access_checks.json`。重启部署后再次读取新 Job 为 `completed`，GLB API 为 200、5,479,468 字节。GPU 进程均已退出。

## 代码与依赖

- `backend/app/models/job.py`、`services/job_service.py`：真实两阶段完成态、未接入第三阶段、范围及旧真实 Job 的只读兼容展示；demo 保留三阶段。
- `backend/app/services/runner_service.py`、`runner_adapter.py`、`api/stages.py`：`run-planned` 串行链、同 Job 依赖、跨 Job 单 GPU 文件锁与排队/取消、超时清理；原 GLIM `/tmp/dump` 独占锁仍在。
- `backend/app/services/upload_service.py`、`api/uploads.py`、`scripts/preflight_ins_bag.py`：受控 profile、流式分块上传、校验、预检和自动注册。`ops/upload_ins_http.py` 是本次真实 HTTP 流式验收客户端。
- `frontend/src/pages/NewJobPage.tsx`、`JobDetailPage.tsx`、`api/api.ts`、状态组件及类型：上传选择/进度/重试/续传、一键创建并启动、范围和逐帧统计、未接入展示。
- `.gitignore`、`README.md`：忽略上传数据副本和自动生成的 dataset JSON；更新 Linux 启动和网页操作说明。
- 前轮已修复的 GLIM SIGINT 后等待正常退出、Livox CustomMsg xyz/reflectivity/逐点时间、PointCloud2 同步过滤、受控 profile、MrHash 逐帧统计及 GLB 自动封装沿用。`backend/requirements.txt` 已声明 `scipy>=1.13,<2`、`fast-simplification>=0.2.0`，本机安装版本见 `runtime/acceptance_environment_versions.txt`；Surface adapter 的正常路径会自动封装，不需手工 package-only。

CPU 回归：`PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -q`，**153 项通过**（本轮新增上传完整性、续传、自动注册、失败预检、两阶段完成态、GPU 队列/取消/超时清理、封装依赖测试）；`cd frontend && npm run build` 通过。前轮 INS CustomMsg 与 Oxford PointCloud2 兼容实读及相关 CPU 测试见 `ops/POSE_SURFACE_INTEGRATION_REPORT.md`。本机版本：FastAPI 0.143.0、Uvicorn 0.54.0、NumPy 2.5.4、trimesh 5.1.1、SciPy 1.18.1、fast-simplification 0.2.0、rosbags 0.11.5、rclpy 3.3.22、sensor_msgs 4.9.2。

## 部署与页面操作

`ops/platform.sh start|status|stop|logs` 管理本部署的 FastAPI 与 Vite。当前地址 `http://127.0.0.1:5173`；API `http://127.0.0.1:8000/api`。从远端电脑访问时需将这两个本机端口按现有主机登录方式转发。在“新建任务”页选择原始 `.bag` 与受控 INS profile，点击“上传、预检并自动注册”；随后选择新数据集，点击“创建并一键运行”。任务详情页显示 Pose/Surface 范围、状态、计数、日志、预览及下载，Distance 为“未接入”。

本轮通过 HTTP API 实测上传、预检、自动注册及任务创建/启动。当前环境未提供浏览器自动化运行条件；网页构建和 HTTP 可访问性已验证，浏览器点击全流程留待人工操作确认。

## 未完成的验收与参数依据

交接配置中的 `T_lidar_imu=[0.011,0.02329,-0.04412,0,0,0,1]`、`acc_scale=9.80665`、逐点相对时间与 `1e-9` 比例原样使用。来源为交接配置，原始标定、坐标方向及 IMU 原始单位依据待负责人确认。本轮不验证完整 Surface、建图精度或第三模块；不修改原始数据、算法及 TSDF 参数。
