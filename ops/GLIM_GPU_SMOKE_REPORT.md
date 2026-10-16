# GLIM GPU 短段验收（2026-10-15）

## 结果

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| GPU 环境 | 通过 | RTX 4090，驱动 595.71.05；真实 `libcuda.so.1` 91,501,576 bytes、`libnvidia-ml.so.1` 2,621,336 bytes，`nvidia-smi` 正常；见 `runtime/gpu_smoke_20261015_02/environment_preflight.txt` |
| 无界面运行 | 通过 | `DISPLAY` 为空；节点加载 GPU odometry、submapping、global mapping，没有 DISPLAY/GLFW/viewer 错误，运行时 GPU 使用约 506 MiB；见 `node.log` |
| 正常退出与新轨迹 | 通过 | 桥接器退出码 0；`dump_on_unload=true` 下向节点发 SIGINT，节点退出码 0；本次 `/tmp/dump` 移入独立目录，`traj_lidar.txt` 非空（238 行）；见 `run_status.json`、`node.log` |
| 时间戳关联 | 已完成，质量门限未通过 | 238/250 = 95.2%，低于固定 98% 门限；全部匹配帧残差 0 ns，重复使用 0、逆序 0；见 `association.json` |
| Surface handoff | 阻断 | 短段初始化丢失头部 11 帧，尾部 1 帧，内部 0 帧；未降低门限、未补造位姿。`poses.txt` 按平台失败分支保留原生 sensor 时间，不能供要求 bag record 时间的 MrHash 使用。|

GPU 短段本身启动、处理和退出成功。关联比例不足是短段边界与初始化造成的 handoff 质量问题，不代表 GLIM 启动失败。

## 本次运行与产物

工作目录：`/root/autodl-tmp/3d-mapping-platform-deploy`。完整入口命令：

```bash
python3 ops/glim_gpu_smoke.py /root/autodl-tmp/3d-mapping-platform-deploy/runtime/gpu_smoke_20261015_02
```

入口使用现有 `ops/glim-child.sh` 分别执行 `node` 和 `bridge`，完整参数数组记录在 `runtime/gpu_smoke_20261015_02/run_status.json`。桥接参数是原始 INS bag、原始 LiDAR/IMU 话题、`/ins/points`、`/ins/imu`、原 frame ID、`--max-lidar-frames 250`，总超时 240 秒。约 5 秒启动等待、桥接结束后约 5 秒收尾等待，再 SIGINT 请求正常 dump，最多等待 60 秒。脚本使用平台 `GlimExecutionLock`、`inspect_dump_dir` 和 `ChildSupervisor`，本次锁在运行前不存在，`/tmp/dump` 在取得锁后检查为空缺状态，无历史结果被覆盖；运行后锁释放，`/tmp/dump` 已移入本次目录，子进程均已退出。

本次目录含原始配置副本 `config/`、GLIM 原生 dump `dump/`、独立拷贝 `traj_lidar.txt`、`bag_index.tsv`、`node.log`、`bridge.log`、`association.json`、`trajectory_checks.json`、`poses.txt`、`run_status.json` 和 `environment_preflight.txt`。配置源为 `ops/glim_runtime/config`；GLIM dump 自身另存其实际加载的配置于 `dump/config/`。原始 bag 没有改动。

首次尝试目录 `runtime/gpu_smoke_20261015_01` 仅记录启动错误：`ops/glim-child.sh` 的 `set -u` 使 ROS Humble `setup.bash` 在 `AMENT_TRACE_SETUP_FILES` 处失败，节点未启动、bag 未读取。随后在 source ROS setup 期间暂时关闭 `nounset`，再恢复，第二次即上述唯一追加短段。未更换驱动、参数或算法。

## GPU 与依赖预检

GPU 设备为 `/dev/nvidia5`（容器可见编号）；`nvidia-smi -L` 和查询均正常。驱动库均为系统 `/usr/lib/x86_64-linux-gnu` 中的非空真实库，`ldconfig` 可解析。ROS 节点及 GPU odometry 的 `ldd` 解析 `libglim.so` 到 `/opt/ros/humble/lib`，`libgtsam.so.4`、`libgtsam_points.so.1`、`libgtsam_points_cuda.so.1` 到 `/usr/local/lib`，CUDA runtime 到 `/usr/local/cuda/targets/x86_64-linux/lib/libcudart.so.12`。安装包为 GLIM 1.2.2、GTSAM 4.3.0、gtsam_points 1.2.2；桥接环境同时导入 rosbags、rclpy、sensor_msgs。配置及 17,125,894,059 字节原始 INS bag 均存在。检查时无其他 GLIM 运行任务；未终止其他进程。

## 数据和轨迹核验

桥接器从原始 bag 读取并发布 250 条 Livox LiDAR、4984 条 MID-360 IMU，索引有 250 个数据行，共 4,996,032 点。GLIM 日志记录 GPU 模块加载、IMU 初始状态估计及 global mapping 保存；238 个新原生 LiDAR 位姿进一步证明点云处理。节点没有逐条 IMU 消费计数，因此可确认其处理 IMU 初始化，但不能从日志给出独立的节点 IMU 消费总数。

原生轨迹 238 行，sensor 首尾时间为 `1717493096.801825047`、`1717493120.502804756` 秒。bag index 的首尾 record 时间为 `1717493095803061748`、`1717493120702630408` ns，首尾 sensor 时间为 `1717493095701965809`、`1717493120602700233` ns。record 比相应 sensor/header 时间晚 0.099706259–0.101579952 秒，中位 0.1008327115 秒，不能直接按原生时间供 MrHash 查找。

原生轨迹采用 `T_world_lidar`、平移米、四元数 `qx qy qz qw`。平台严格解析器通过：8 列、有限值、严格递增时间、四元数范数 0.999999495–1.000000500。按已有最近邻代码用 sensor 时间关联原生轨迹，再用 record 时间生成标准 Pose；由于质量门限拒绝，平台契约中的 `poses.txt` 只保留原生 sensor 时间，`run_status.json` 明确标识 `timestamp_basis=lidar_sensor` 和 `surface_handoff_compatible=false`。匹配帧为第 12–249 帧；未匹配第 1–11 帧和第 250 帧，中间无缺帧。所有 238 个匹配的时间残差精确为 0 ns，重复位姿 0，逆序 0。未产生伪装成 record 时间的部分 Pose。

## 参数来源及下一步

当前 `T_lidar_imu=[0.011,0.02329,-0.04412,0,0,0,1]`（IMU 到 LiDAR）、`acc_scale=9.80665`、逐点时间比例 `1e-9`、逐点相对时间及 frame ID 均照现有配置使用。**来源为交接材料，原始依据待第一模块负责人确认**，尤其是外参标定来源、坐标方向、IMU 原始单位与本 bag 的适用性。相机标定未参与本轮。

后续 Livox CustomMsg→MrHash 适配需为 MrHash 增加该 ROS1 消息的 reader/字段映射（xyz、reflectivity、offset_time、frame/header），核对其 bag record 时间查找规则和 Pose 单位/坐标约定，并在具备满足 98% 门限的合法 Pose 后验证逐帧计数与 Surface 输入。此处只列下一步需求，本轮未运行 MrHash、完整序列或 Run All。
