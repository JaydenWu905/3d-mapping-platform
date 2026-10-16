# GLIM 运行环境准备（2026-10-15，CPU 验证）

> 历史安装记录：下文的“当前”和“尚未完成”只代表记录当时。原 INS 样本后续已完成真实 Pose→Surface 工程验收；新序列入口只有 CPU 验证。当前范围见[README](../README.md)和[新序列上传说明](../docs/livox-new-sequence-upload.md)。本记录不证明新机器环境重建。

## 选择与安装

本机 Ubuntu 22.04.5 对应 ROS2 Humble。交接包 `../GLIM_Handoff_INS_20261003/docs/environment.txt` 记录成功环境为 GLIM 1.2.2 CUDA 12.6、GTSAM 4.3、gtsam_points 1.2.2；因此选择作者的 Jammy CUDA 12.6 二进制包。选择依据是交接的已运行版本、系统版本和仓库候选版本，不是 `nvidia-smi` 的 CUDA 字样。本机 `/usr/local/cuda` 仍指向 12.8；没有改动它、NVIDIA 驱动或 MrHash Pixi 环境。

官方依据：[GLIM 安装页](https://koide3.github.io/glim/installation.html)、[ROS Humble Ubuntu deb 安装](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)、[ROS Python 包指南](https://docs.ros.org/en/humble/How-To-Guides/Using-Python-Packages.html)。后两页的可读取官方文档源码快照在 `glim_install_logs/ros_*_official.rst`。ROS 文档建议二进制安装使用同版本系统 Python；也说明官方 deb 与 setup 路径。GLIM [配置说明](https://github.com/koide3/glim/blob/master/docs/quickstart.md)支持绝对 `config_path`；已安装二进制中也含 `config_path`、`dump_on_unload` 和 `/tmp/dump` 字符串，交接有该参数成功运行记录。

先安装官方 `ros2-apt-source` 1.3.0 Jammy 包，再配置作者的 `ubuntu2204` 签名源并 `apt-get update`。事务查询记录在 `glim_install_logs/apt_simulation_selected.txt`：10 个依赖包升级、341 个新包、0 移除。正式执行的是 `apt-get install --no-install-recommends ros-humble-ros-base ros-humble-glim-ros-cuda12.6 python3.10-venv`，没有执行全系统 upgrade。APT 通过包依赖自动安装 GTSAM、gtsam_points、GLIM 与所需 ROS 包。完整记录：`apt_update.log`、`apt_install.log`、`packages_before.tsv`、`packages_after.tsv`、`sources_before.list`、`source_files_before.txt`、`source_files_after.txt`、`sources_added.txt`、`ldconfig.log`。安装后按 GLIM 要求显式执行了 `ldconfig`。

| 已安装包 | 版本 |
| --- | --- |
| `ros-humble-ros-base` | `0.10.0-1jammy.20260915.225919` |
| `ros-humble-glim-ros-cuda12.6` / `ros-humble-glim-cuda12.6` | `1.2.2-0jammy` |
| `libgtsam-notbb-dev` | `4.3.0` |
| `libgtsam-points-cuda12.6-dev` | `1.2.2` |
| `ros-humble-rclpy` | `3.3.22-1jammy.20260907.213431` |
| `ros-humble-sensor-msgs` | `4.9.2-1jammy.20260907.212033` |

## 路径与隔离

ROS setup 为 `/opt/ros/humble/setup.bash`，包索引给出 `glim_ros` 前缀 `/opt/ros/humble`，节点为 `/opt/ros/humble/lib/glim_ros/glim_rosnode`（见 `ros_index.txt`）。`libglim.so` 和 GPU 插件在 `/opt/ros/humble/lib`；APT 安装的 GTSAM 4.3 与 gtsam_points 1.2.2 均在 `/usr/local/lib`，有 `dpkg -S` 所有权证明。`ldd_glim.txt` 显示节点、GPU odometry、submapping、global mapping 全部解析到这组库，未见 `not found`。CUDA runtime 解析到现有 `/usr/local/cuda/targets/x86_64-linux/lib/libcudart.so.12`。因此 ROS setup **之后**，只在 GLIM/桥接子进程中前置 `/usr/local/lib`；本机并未盲用历史路径。

独立桥接环境是 `/root/autodl-tmp/envs/glim_bridge/bin/python`，Python 3.10.12。用 `/usr/bin/python3.10 -m venv` 创建，装 `rosbags==0.11.5`。为兼容平台的工作区路径检查，将 venv 的 `python3.10` 入口改为系统解释器二进制的本地副本，保留 `pyvenv.cfg`；它仍是 Python 3.10 的隔离 venv。`bridge_import.txt` 证明同一解释器导入 rosbags 0.11.5、rclpy 3.3.22、sensor_msgs 4.9.2，以及桥接实际使用的类。正确顺序：在子进程 shell 中 `source /opt/ros/humble/setup.bash`，再 `export LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH:-}`，最后调用绝对桥接解释器。未把 ROS `PYTHONPATH` 或实际 `LD_LIBRARY_PATH` 写入全局启动文件、FastAPI、Node 或 Pixi。

## 无界面配置与平台读取

运行候选复制自 `../GLIM_Handoff_INS_20261003/glim_ins_config` 到 `ops/glim_runtime/config`，原交接目录未修改。运行副本的 `config_ros.json` 已移除 `librviz_viewer.so`；`libstandard_viewer.so` 原本没有加载。保留 `libmemory_monitor.so`。`config.json` 仍选择 GPU odometry、GPU submapping、GPU global mapping。`config_cpu_validation.txt` 证明全部配置可按平台 JSONC 解析且引用文件存在；`plugin_validation.txt` 证明三个 GPU 插件和 memory monitor 均在安装目录，且运行配置无 viewer。`config_viewer.json` 仍作为未加载的参数文件保留，不会仅因被引用而打开窗口；实际无界面启动仍待 GPU 模式验证。

`ops/glim-runtime.env` 存放平台支持的 `GLIM_*` 覆盖值。平台的 `pose_spec.resolve_glim_runtime` **只接受工作区相对的配置及桥接解释器路径**，所以环境文件使用相对路径；解析后的绝对路径见 `glim_install_logs/runtime_resolution.txt`。`ops/platform.sh` 已实际 source 该文件，再启动后端；进程环境已核实含这五个 `GLIM_*` 值，不含 ROS `PYTHONPATH` 或实际 `LD_LIBRARY_PATH`。后端与前端健康检查通过。`ops/glim-child.sh` 将同样的相对路径解析成绝对路径，供独立运行。平台 adapter 使用 `--ros-args -p config_path:=<effective-config-dir> -p dump_on_unload:=true`；当前 1.2.2 二进制含这些参数和 `/tmp/dump` 路径，最终导出效果仍待 GPU 运行。

## 原始 bag 的只读 CPU 验证

原始输入 `/root/autodl-tmp/INS/2024-06-04-16-24-55.bag`，17,125,894,059 字节。使用桥接 venv 执行 `ops/inspect_ins_bag_cpu.py`，只读取连接表与前三个 Livox 消息，没有发布话题或回放。完整结果见 `bag_cpu_inspection_bridge.txt`。LiDAR `/livox_mid360/livox/lidar` 是 `livox_ros_driver2/msg/CustomMsg`，1539 条；MID-360 IMU `/livox_mid360/livox/imu` 是 `sensor_msgs/msg/Imu`，30770 条。首帧 `point_num=20160`，实际点数一致，`offset_time` 为 0 至 100329213，首点 xyz 约 `(-1.553,-1.507,0.241)`，reflectivity 72；header 为 `1717493095701965809 ns`，bag record 为 `1717493095803061748 ns`。第二、三帧也核对了这些字段。逐点时间按 handoff 的纳秒定义乘 `1e-9`；不能用 bag record 时间冒充传感器 header 时间。

交接 `README_交接.md`、运行配置与平台 INS profile 一致给出 `T_lidar_imu=[0.011,0.02329,-0.04412,0,0,0,1]`（IMU 到 LiDAR）、`acc_scale=9.80665`、`perpoint_relative_time=true`、`perpoint_time_scale=1e-9`、LiDAR frame `livox_mid360_frame`、IMU frame `livox_frame`。独立运行的桥接输出话题是 `/ins/points` 和 `/ins/imu`；平台 Job 会将有效配置和桥接话题同时覆盖为默认 `/mapping/glim/points`、`/mapping/glim/imu`。LiDAR header frame 已从 bag 实读核对。外参的原始标定来源及 IMU 原始单位的独立测量证据不在交接包中；正式长段运行前请第一模块负责人确认其来源、坐标方向及此 bag 的适用性。相机参数虽在交接配置中，但本轮只用 LiDAR 与 IMU，未验证相机标定。

## 当前边界与切回 GPU 后的命令（本轮未执行）

当前无 `/dev/nvidia*`。`libcuda.so.1` 和 `libnvidia-ml.so.1` 的目标文件长度为 0；这是当前无卡模式的驱动映射状态。`ldd` 对已安装 GLIM/ROS 常规依赖没有缺项，但 GPU 初始化、CUDA 12.6 包与当前 12.8 runtime 的实际兼容性、无界面运行、退出 dump 均需 GPU 模式实测。不要在此模式安装替代驱动或伪造 `.so`。

1. 预检（只读）：

   ```bash
   cd /root/autodl-tmp/3d-mapping-platform-deploy
   nvidia-smi -L
   test -e /dev/nvidia0
   test "$(stat -Lc %s /usr/lib/x86_64-linux-gnu/libcuda.so.1)" -gt 0
   source ops/glim-runtime.env
   bash -lc 'source /opt/ros/humble/setup.bash; export LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH:-}; ros2 pkg prefix glim_ros; ldd /opt/ros/humble/lib/glim_ros/glim_rosnode | grep "not found" || true'
   test ! -e /tmp/dump   # 若已有结果，先人工识别和保存，勿覆盖
   ```

2. 第一模块独立短段（两个终端，同一台 GPU 机器；先启动 A，待节点订阅后运行 B）。不经过平台 Job、MrHash 或 Run All：

   ```bash
   # 终端 A
   cd /root/autodl-tmp/3d-mapping-platform-deploy
   ops/glim-child.sh node 2>&1 | tee ops/glim_install_logs/gpu_short_node.log
   ```

   ```bash
   # 终端 B
   cd /root/autodl-tmp/3d-mapping-platform-deploy
   ops/glim-child.sh bridge \
     --bag /root/autodl-tmp/INS/2024-06-04-16-24-55.bag \
     --lidar-topic /livox_mid360/livox/lidar \
     --imu-topic /livox_mid360/livox/imu \
     --points-out /ins/points --imu-out /ins/imu \
     --lidar-frame livox_mid360_frame --imu-frame livox_frame \
     --bag-index /root/autodl-tmp/3d-mapping-platform-deploy/ops/glim_install_logs/gpu_short_bag_index.tsv \
     --max-lidar-frames 300 2>&1 | tee ops/glim_install_logs/gpu_short_bridge.log
   ```

3. B 结束后等待约 5 秒，再在 A 终端按 `Ctrl+C` 请求 `dump_on_unload` 导出。检查 `ops/glim_install_logs/gpu_short_{node,bridge}.log`、`gpu_short_bag_index.tsv` 和 `/tmp/dump/{traj_lidar.txt,config}`。重点检查启动模块、收到点云和 IMU 的计数、首尾时间、退出码、是否有崩溃与 dump 完整性。历史交接记录曾在 dump 完成后退出时段错误；若重现，须保留日志并核对实际文件，不可只看退出码。不要把交接的历史 `traj_lidar.txt` 当成本次 Job 输出。

独立 GLIM 验证通过后，再验证平台 Pose 的同 Job `bag_index.tsv`、新轨迹关联率和时间残差，随后处理 Livox `CustomMsg` 到 MrHash 的 reader/配置与逐帧处理计数。当前仅注册 Oxford 数据集；INS 的平台 Job 注册与 Surface 衔接尚未完成。本轮没有运行 GLIM、MrHash、Run All 或生产前端构建。
