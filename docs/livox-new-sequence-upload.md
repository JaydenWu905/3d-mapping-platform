# 同设备 Livox 新序列上传（CPU 预检版）

当前上传页提供两种独立选择：原 INS 样本的固定 SHA profile，以及 `ins_livox_mid360_same_rig`。后者只面向与原 INS 样本**同一物理 MID-360、IMU、安装和采集配置**的新序列。服务器维护设备配置；用户不能上传脚本、标定文件、任意话题或算法配置。现有外参与加速度单位仍是**交接配置，原始依据待确认**，选择 profile 不构成标定核准。

真实算法还依赖独立 MrHash 源码与环境；取得状态见[外部依赖说明](MRHASH_DEPENDENCY.md)。

## 操作

1. 准备单个 ROS1 bag v2.0 `.bag`，大小 1 字节至 64 GiB。选择“同设备同采集配置（待确认标定）”，确认设备、安装和采集配置相同后上传。页面按 64 MiB 分块并支持按 offset 续传。
2. 完成上传后等待服务器对整包计算 SHA-256 并流式执行 CPU 预检。页面显示实测 LiDAR/IMU 条数、LiDAR header 时间范围、检查的点数、提示或拒绝原因。同 SHA 的已注册上传复用原数据集 ID；原固定样本须选固定样本 profile。
3. 预检通过才会注册新数据集。选择它创建任务；“完整运行”对应本次 bag 全部 LiDAR 帧，“短段验证”仅将 Surface 限于原始第 1–100 帧，两者的 Pose 均使用本次完整 bag。本轮没有运行真实算法，新序列端到端性能未验收。

## 输入与检查

- LiDAR：`/livox_mid360/livox/lidar`，`livox_ros_driver2/msg/CustomMsg`。`header.stamp`、`timebase`、`point_num`、`points` 必需；每点的 `x/y/z`、`reflectivity`、`offset_time` 必需。点坐标单位为米，逐点偏移为相对 header 时间的纳秒。
- IMU：`/livox_mid360/livox/imu`，`sensor_msgs/msg/Imu`。读取 header 时间、角速度、加速度及姿态；`orientation_covariance[0] == -1` 时按 ROS 约定允许姿态不可用。交接配置假定加速度原值为 g、GLIM 比例为 9.80665；程序不从数值推测单位。
- LiDAR `header.frame_id` 必须为 `livox_mid360_frame`，IMU 为 `livox_frame`。设备 profile 保存 `T_lidar_imu=[0.011,0.02329,-0.04412,0,0,0,1]`、逐点时间比例 `1e-9`、GLIM 配置目录及 MrHash `ins_livox_mid360_custom` 配置；这些是交接值，程序不能证明它们适用于上传文件。bag record 和 header 时间均按纳秒统计，逐点偏移相对 LiDAR header；Pose 按 header 时间关联，MrHash 由 bag record 时间查找对应 Pose。
- 全包逐条检查解析、话题类型及 header 帧 ID、非空帧、点数、点和 IMU 关键值有限、每话题的 record/header 时间严格递增、Livox `timebase` 与 header 相差不超过 0.05 秒、点偏移 0–1 秒、每个 LiDAR 帧经 MrHash 0.2–100 米范围滤波后仍有点，以及 IMU header 时间与 LiDAR 至少 95% 重叠。这些条件失败会拒绝注册。
- IMU 内部时间间隔超过 1 秒会拒绝；未覆盖 LiDAR 两端、内部时间间隔超过 0.2 秒，或最大逐点偏移超过 0.2 秒会提示。不同设备、安装或时间语义不能仅凭相同消息类型通过来源确认。
- 预检只确认结构与所选设备配置的运行前提；GLIM Pose 关联仍要求 98% 覆盖、0.05 秒容差、无重复 Pose 使用，MrHash 还要求 bag record 时间与 Pose key 相差不超过 1000 ns。预检不保证算法成功或建图精度。
- 当前继承的 Pose 运行超时为 1200 秒；上传没有单独的采集时长上限。较长序列即使通过 CPU 预检，运行时仍可能超时；这需要另行验证和调整运行策略。
- 文件须为单个 `.bag`，容量 1 字节至 64 GiB，块上限 64 MiB；CPU 预检最长 3600 秒。预检按实际消息流统计，不要求原样本大小、SHA 或 1539/30770 条数。固定样本 profile 则仍要求原大小、SHA 和消息数。

每份新序列的 SHA、大小、实际消息数、record/header 时间范围和预检结果保存在新数据集配置中。同设备参数现位于 `backend/config/upload_devices/ins_livox_mid360_same_rig.json`；其他自采设备按 [换设备修改指南](换设备修改指南.md) 新增独立 ID。新序列不会继承原样本的 1539/30770 条消息数或截止时间。当前 bridge/MrHash reader 只支持上述 ROS1 Livox CustomMsg/IMU 结构；其他消息格式需一次性适配。

真正新采集序列的端到端验收仍需来源和标定依据明确的 bag，经独立审查后另行运行 Pose→Surface 并核查时间关联、帧统计、结果与精度。合成 bag CPU 测试和重传原 INS bag 均不能替代该验收。

## 上传 API

网页调用 `GET /api/uploads/profiles` 取得服务器可选配置，`POST /api/uploads` 提交 `filename`、`size_bytes`、`profile_id`；新序列还须提交 `attested_same_rig=true`。返回的 `upload_id` 只标识本次传输。客户端用 `GET /api/uploads/{upload_id}` 查询服务端 offset，以 `PUT /api/uploads/{upload_id}/chunk` 传块，带 `X-Offset` 与 `X-Chunk-Sha256` 请求头；最后 `POST /api/uploads/{upload_id}/finalize` 计算整包 SHA、预检并注册。失败不会出现可选数据集；同设备配置快照下相同内容会复用已有数据集 ID。`POST /api/jobs` 需选择已注册数据集，`run_mode=full|short`；当前网页真实入口只规划 Pose、Surface 两阶段；main 已接入 Distance/ESDF 后端，但本流程未请求或验收第三阶段。不得将预检成功等同于启动算法。
