# 第三模块 (Distance / ESDF) 云端部署与集成指南

本模块负责将上游（Surface 阶段）生成的体素点云，转化为全局 ESDF（欧几里得符号距离场）地图，并生成可视化的切片图片。核心算法使用 C++ (Voxblox) 实现，后处理使用 Python。

## 1. 架构与调度逻辑

*   **调度方式**：后端通过 `SubprocessRunnerAdapter` 调用 `run_esdf.sh`。该脚本读取上游的 `stage2_surface/result_manifest.json` 中的 `voxel_points` 路径作为输入。
*   **核心执行**：`run_esdf.sh` 依次调用编译好的 C++ 程序（生成 `.esdf` 和点云 `.ply`）以及 Python 脚本 `esdf_postprocess.py`（生成红蓝渐变切片图）。
*   **产物登记**：所有产物写入 `stage3_esdf/`，并生成 `result_manifest.json` 供前端解析渲染。

## 2. 环境要求与依赖

*   **系统**：Ubuntu 20.04 / 22.04
*   **编译工具**：`cmake` (>= 3.10), `g++` (支持 C++17)
*   **核心依赖**：Eigen3, PCL, Protobuf, Glog, Gflags（脚本会自动 apt 安装）
*   **ROS 依赖**：**必须安装 `catkin_tools`** 用于编译底层的 Voxblox 库。若未安装，请执行：

```bash
sudo apt install python3-catkin-tools
```

## 3. 一键编译部署

进入 `backend/scripts/` 目录，执行：

```bash
chmod +x build_esdf.sh
./build_esdf.sh
```

脚本执行流程：

1.  自动安装系统底层依赖。
2.  网络下载：默认使用 `ghfast.top` 镜像拉取 Voxblox 源码及其子依赖。如果您的服务器网络依然受限导致超时，请为当前终端配置全局 HTTP 代理（例如 `export http_proxy=http://your_proxy:port`）。
3.  在 `third_party/voxblox_ws` 隔离空间内编译 Voxblox。
4.  在 `esdf_cpp/build` 下编译 C++ 可执行文件。

## 4. 重新编译与清理

如果代码更新或编译失败需重新开始，请先清理缓存：

```bash
rm -rf backend/scripts/esdf_cpp/third_party
rm -rf backend/scripts/esdf_cpp/build
./build_esdf.sh
```

## 5. 路径与关键变量配置

### C++ 可执行文件路径

默认路径：`backend/scripts/esdf_cpp/build/voxel_points_to_esdf`

如果修改了编译路径，可在 `run_esdf.sh` 中修改 `DEFAULT_EXE` 变量。

支持通过环境变量覆盖：

```bash
export ESDF_EXECUTABLE=/path/to/your/exe
```

### 输入文件路径

默认自动从 `<job_dir>/stage2_surface/result_manifest.json` 中提取 `artifact_id="voxel_points"` 的路径。无需手动干预。

### 输出文件路径

固定写入 `<job_dir>/stage3_esdf/` 目录下：

*   `map.esdf`（二进制 ESDF 地图）
*   `preview/esdf_vis.ply`（可视化点云）
*   `preview/slice_xy.png`、`preview/slice_xz.png`、`preview/slice_yz.png`（三视图切片）

### 算法参数

体素大小和波前传播距离在 `run_esdf.sh` 中作为参数传入，默认 `--voxel_size 0.1 --max_esdf_distance 2.5`。