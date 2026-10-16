# INS 第一、第二模块真实数据交接报告（2026-10-15）

## 结论与边界

本次新建平台 Job：`job_1792049139_57c00d`，目录为 `jobs/job_1792049139_57c00d/`。完整原始 INS bag 的 GLIM Pose 阶段与前 100 条原始 LiDAR 消息的 MrHash Surface 阶段均完成。Pose→Surface handoff **通过**：1527/1539 帧关联，99.2203%，高于原有 98% 门限；最大时间差仍为 0.05 秒，重复使用上限仍为 0。此结果只验证工程链路与基本输出，不宣称建图精度达到项目指标。未运行 RGB-D、第三模块、Run All；未修改原始数据、融合算法或 TSDF 参数。

最终 Job 的 Pose、Surface 状态为 `completed`，Distance 为 `waiting`。平台 API 产物登记、GLB 预览和下载均返回 HTTP 200，逐项字节数见 `jobs/job_1792049139_57c00d/api_access_checks.json`。本次完整命令和两次受控恢复经过见同目录的 `command_history.txt`。

## 第二模块 CPU 准备

检查发现原代码只解析 PointCloud2，Surface adapter 固定 Oxford 配置，runner 的帧上限按已返回的 Pose 帧计数，无法可靠限定原始 INS 前 100 帧。现已补齐：

- MrHash `Ros1Reader` 显式接受 Livox `CustomMsg` 和 Oxford `PointCloud2`，按原始 bag record 时间匹配 Pose。Livox 的 `point_num` 与实际点数必须一致；xyz、reflectivity 和 `offset_time`（纳秒）解析为点数组与归一化逐点扫描时间，长度一致，非有限值和空有效点集会报错。融合算法仍只消费 xyz，未修改算法。
- PointCloud2 的有效点掩码同步应用到逐点时间，距离按 xyz 计算。实读 Oxford 一帧得到 76,090 个有效点和 76,090 个时间值；实读 INS 一帧得到 18,447 个范围内有效点和等长时间值，首点 xyz/reflectivity 与 bag 预检一致。
- 平台按注册的受控 `mrhash_profile` 和 topic 选择配置；INS 为 `ins_livox_mid360_custom`，Oxford 为 `oxford_hesai_pointcloud2`。INS 配置沿用 Oxford 模板的 map/mesh 数值，仅指定 Livox topic、路径和帧范围；没有调整 TSDF。
- Surface 输入仍从**同一 Job** 的 Pose result manifest 中解析 `registered_trajectory`，校验路径、大小、SHA-256、`T_world_lidar`、米、四元数顺序和 bag record lookup key；handoff 不兼容时拒绝运行。原始 bag 的注册大小和 SHA-256 也在准备及启动时验证。
- runner 的 `start_frame=1,end_frame=100` 指原始 LiDAR topic 的 **1 起始、两端包含** 范围，先计入选中，再因缺 Pose 跳过，不会把第 101 帧补进范围。

CPU 验证：平台 59 个相关 unittest 通过（`test_glim_pose_adapter`、`test_surface_input`、`test_glim_dataset_and_dispatch`、`test_mesh_preview`）；Pixi 下实读原始 INS CustomMsg 的前三帧，选中 3、跳过无 Pose 的首帧 1、返回 2；另实读 Oxford PointCloud2 与 INS CustomMsg 各一帧，点、时间长度及有限值检查通过。INS 注册数据集校验无错误。首次批量测试暴露旧 fixture 没有 profile 和 0.2 秒假节点启动竞态，已修正 fixture，复测通过。

## 完整 GLIM Pose

使用原始 `/root/autodl-tmp/INS/2024-06-04-16-24-55.bag`，全序列桥接器实际读取并发布 **1539 条 LiDAR、30770 条 IMU**；`stage1_pose/native/bag_index.tsv` 有 1539 个数据行。GLIM 加载无界面 GPU 模块，使用 `stage1_pose/native/config/` 的本 Job 有效配置。原生 `traj_lidar.txt` 1527 行，标准 `stage1_pose/poses.txt` 1527 行，全部位姿有限、时间严格递增，四元数范数在 0.999999376–1.000000663。两份轨迹的位姿变换逐行相同，时间列分别属于 sensor/header 与 bag record。

| 时间项 | 首 | 尾 |
| --- | --- | --- |
| 原生轨迹 sensor 秒 | `1717493096.801825047` | `1717493249.402045488` |
| 标准 Pose record 秒 | `1717493096.902776480` | `1717493249.502683640` |
| bag_index record 纳秒 | `1717493095803061748` | `1717493249602701942` |
| bag_index sensor 纳秒 | `1717493095701965809` | `1717493249502075434` |

每帧 record 比 sensor 晚 0.099372210–0.101943679 秒，中位 0.100730945 秒。关联采用已有 sensor 时间最近邻代码；1527 帧匹配，12 帧跳过，比例 0.992203。匹配残差最大 0 ns，重复位姿 0，逆序 0；头部缺第 1–11 帧，尾部缺第 1539 帧，内部缺 0 帧。门限未降低、没有补造位姿或固定时间偏移。`stage1_pose/native/association.json`、`stage1_pose/pose_checks.json` 保存详细统计。

首次完整 Pose 运行已成功关联，但平台在第一轮 dump 刚出现时过早向 GLIM 发送 SIGTERM，节点退出码 -15。其全部证据保存在同 Job 的 `pose_attempt1_exit_issue/`。修复为 SIGINT 后等待 GLIM 自行退出，再验证退出码及 dump；唯一一次完整 Pose 重试重新生成全部索引、配置和轨迹，节点退出码 **0**，桥接器退出码 **0**，GPU 资源释放。最终 Surface 只消费这次重试生成的标准 Pose。运行命令、配置覆盖、环境来源、锁与 `/tmp/dump` 隔离记录在最终 Pose manifest 和日志；环境包版本另见 `environment_versions.txt`。

交接参数 `T_lidar_imu=[0.011,0.02329,-0.04412,0,0,0,1]`、`acc_scale=9.80665`、逐点相对时间及 `1e-9` 比例均原样使用。**来源为交接配置，原始标定及单位依据待第一模块负责人确认**；本次不以轨迹视觉效果反调参数。

## 同 Job 的 Surface 短段

首次 Surface 启动发现普通 Job 的 `full` 模式生成 `end_frame=-1`，在约 13 个返回帧时立即取消，证据保存在 `surface_attempt1_cancelled/`，未登记为成功。修复为 INS 注册数据集受控设置 `integration_end_frame=100` 后，唯一一次 Surface 算法重试使用 `stage2_surface/runs/20261015_153740_3d46e2af/mrhash.cfg`：Livox topic、原始帧 **[1,100]**，对应原始 bag 与本 Job 已通过质量门限的标准 Pose。

本次 MrHash 算法实际 **选中 100、成功关联 Pose 89、无 Pose 跳过 11、融合 89**。跳过的是 GLIM 初始化缺失的第 1–11 帧；没有使用无效位姿、固定偏移或历史轨迹兜底。`raw/frame_accounting.json` 与算法日志记录了计数。算法生成了新的原生 mesh、voxel、hash 产物。

算法结束后 GLB 封装因平台 venv 缺少 SciPy 而落入 trimesh 极慢的逐顶点法；停止封装进程后安装并声明 `scipy>=1.13,<2`。随后以同次真实算法写出的 raw 产物执行 **package-only** 校验和预览生成，没有再次运行 MrHash 融合。封装成功并完成几何校验后，通过 `JobService` 将 Surface 状态与已验证的 result manifest 对齐；`backend_details.packaging_resumed_from_raw_run=true` 明确记录这一步。

| 本次产物 | 数量与检查 |
| --- | --- |
| 原生 mesh | 248,723 顶点、199,383 面；包围盒 `[-2.875,-11.6735,-0.825]` 至 `[26.9229,4.12544,3.88324]` 米 |
| voxel | 1,034,191 点；xyz、sdf、weight 全有限；sdf 约 `[-0.4,0.4]` |
| hash | 6,608 点；xyz、weight 全有限 |
| GLB 预览 | 109,700 顶点、199,383 面，5,465,692 bytes；有限包围盒，与 mesh 源包围盒一致 |

`stage2_surface/result_manifest.json`、`stage2_surface/geometry_checks.json` 和本次 `runs/.../raw/` 保存产物及核验。平台 API 对 GLB 预览、mesh、voxel、hash、配置、帧统计，以及 Pose 的标准轨迹、原生轨迹、关联报告和索引均返回 HTTP 200，内容非空。下载验证记录在 `api_access_checks.json`。

## 尚待确认与后续

外参原始标定、坐标方向、IMU 原始单位及其对本 bag 的适用性尚待负责人确认。此次只证明时间戳与产物交接、真实 GPU 算法处理和基础几何有效；不包含独立真值误差或精度验收。第三模块仍未接入，本轮没有启动它，也没有执行 Run All。
