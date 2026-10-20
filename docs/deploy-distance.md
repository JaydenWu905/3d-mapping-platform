# Distance 云端部署、实际契约与验收（2026-10-20）

> 当前状态：代码已接入；隔离 catkin 工具与固定源码已准备；平台 CPU 检查通过；Voxblox/转换器尚未编译；真实 Distance 与新 Job 完整三模块验收均未通过。不要执行旧版无参数“一键安装”流程，也不要把演示结果作为真实成功。

## 实际代码与环境

平台基线 main `01fd3fc` 已包含 PR #4、#7、#8 和新前端。PR #8 的转换器原始源码是同一平台仓库的 `backend/scripts/esdf_cpp/voxel_points_to_esdf.cpp`，提交 `c2120cb4cf7be7008cb6d856021e32b3570dd1c8`；不是子模块，也没有另一个必须从原作者机器复制的转换器仓库。

`CMakeLists.txt`、`build_esdf.sh`、`run_esdf.sh`、`esdf_postprocess.py` 构成可重建材料，没有随附已验收镜像或服务器二进制。原 PR 下载浮动 Voxblox，优先 colcon，使用全核编译，并依赖本机路径；本轮已改成显式 fetch/preflight/build，核心源码锁在 `ops/distance-sources.lock.json`。Voxblox 固定 `c8066b04075d2fee509de295346b1c0b788c4f38`，catkin 及七个库包装依赖也各有精确提交。锁文件是本轮选择的待验证构建基线，不表示原作者验收过这些版本。

本机 Ubuntu 22.04。Voxblox 核心库使用 ROS1 **catkin 构建系统**，本流程只编译 `voxblox` 及依赖，不编译 `voxblox_ros`，不需要 roscore/ROS 消息节点。catkin 源码来自 noetic-devel 固定提交，不代表已装 ROS Noetic。`/opt/ros/humble` 仍只供 GLIM ROS2 子进程使用，绝不 source 到 Distance 或后端。

路径：

- 源码：`/root/autodl-tmp/envs/distance/ws/src/`。
- Python 3.10 构建工具：`/root/autodl-tmp/envs/distance-tools/`；直接依赖固定于 `ops/distance-tools.requirements.txt`，实际完整 freeze 在本轮证据目录。
- 未来库安装：`envs/distance/ws/install/`。
- 未来候选程序：`envs/distance/converter-build/voxel_points_to_esdf`，构建后才设置 `ESDF_EXECUTABLE`，设置此变量本身不会解除契约阻断。
- 运行入口：平台 `SubprocessRunnerAdapter → run_esdf.sh`，继承平台取消、进程组清理、超时和日志机制；默认 Distance 超时 1200 秒。

已存在 Eigen 3.4、Protobuf 3.12.4、PCL 1.12.1、CMake/g++/protoc；缺系统 glog/gflags 开发包。PCL 并未被当前转换器包含或链接，不再为它额外安装大型依赖。catkin-tools 0.9.5、catkin-pkg 1.1.0、empy 3.3.4、PyYAML 6.0.3、rospkg 1.6.0 已安装到独立 venv。没有改动 GLIM/MrHash、系统 swap、CUDA、驱动、全局 ROS 或 shell 初始化。

## 源码确定的 Surface→Distance 契约

输入必须是**同一个 Job** `stage2_surface/result_manifest.json` 声明的 `voxel_points`，不是 Mesh、GLB 或 `navigation_input`。原脚本 Mesh 回退已移除。输入要求 completed、非 mock、world/meter，且路径在该 Surface 目录内。

转换器按 24 字节结构盲读，所以包装器严格要求 binary_little_endian PLY：float32 `x y z sdf weight`，uint8 `red green blue alpha`，字段顺序完全一致，仅 vertex element，数量和文件长度匹配。正式启动前流式检查有限值、weight>0，至少一条满足转换器的 weight>=2；不把输入一次装进内存。

MrHash 本机源码 `23c98bb09eaf1fe06f54153b046b506303ce599d`：

- `voxel_data_structures.cu` 的 LiDAR 分支使用 `range - voxel_range`（或法向投影），正值在传感器侧，米制未归一化；按 `sdf_truncation + range*sdf_truncation_scale` 截断（准确公式见同目录 getTruncation），没有除以截断距离。本机 INS 配置为 0.40 m、scale=0，不能套用于所有任务。
- `streamer.cpp::serializeData` 只导出 weight>0；未知/缺席体素不导出。weight 是积分权重，不是概率；转换器另行过滤 weight<2，与 Mesh 的 min_weight_threshold=10 不是同一规则。
- **本次实际导出公式**为 `block_pw + dl*virtual_voxel_size`，没有显式加半体素；不能直接沿用历史“导出中心”的说法。必须在统一网格转换前处理坐标采样约定。
- `descs[k].resolution` 决定间距 `virtual_voxel_size * 2^resolution`；一个文件混合自适应层。颜色能标识部分层，但并非可靠完整的体素 extent 元数据。0.05 m 仅是 INS 的 finest virtual size。不能直接用转换器默认 0.1 m，也不能仅把它换成0.05 m就视为解决。
- `distance_input.py` 从本 Job `run_config` 读取 virtual size；在缺少经验证的 `backend_details.distance_grid={uniform:true, voxel_size_m:...}` 时拒绝正式转换。该字段必须由真实均匀层导出/重采样流程生成并记录来源，不能手工伪造它来绕过校验。

当前 C++ 转换器的问题完全可由源码确定，无须向负责人重复确认：它直接把投影 sdf 写为 EsdfVoxel.distance；以 abs(sdf) 为起点，26 邻域步长扩张到2.5 m；未知邻居被写为 observed=true 且总为正距离；首次发现即 processed，没有最短路松弛；不能据此保证欧氏符号距离或保留未知区。这是算法契约阻断，恢复 GPU 或仅成功编译均不会自动解决。当前平台与脚本明确拒绝真实 Distance，演示仍明确为 mock。

需后续完成：采用经验证的 TSDF→ESDF 流程（固定 Voxblox 源码已有 `test/tsdf_to_esdf.cc` / EsdfIntegrator 供参考），明确投影 TSDF 的使用方式、已观测区域、负区域、截断和未知区政策；建立自适应→均匀网格及坐标约定，并用解析平面/球验证误差、符号与未知区域。完成后更新 `distance_readiness.py` 的静态阻断，并以真实构建和测试结果生成依赖/就绪状态；不能直接删除原因字符串冒充验收。

## 原生产物、预览与验证要求

`map.esdf` 是 Voxblox Layer<EsdfVoxel> 的 Protobuf 序列化，不是 NumPy/通用点云。必须由同版本 `io::LoadLayer<EsdfVoxel>` 重新读取，核对 voxel size、voxels_per_side=16、非零块/observed 数、有限距离、符号、已知/未知样本；文件非空只能做最基本的存在性检查。原程序未检查 saveToFile 的 bool，后续修复时必须处理它。

`preview/esdf_vis.ply` 是 ASCII `x y z distance red green blue`，仅导出 |distance|<=1.5 m 的 observed 体素；原源码使用 grid origin 坐标，不是完整 map 的覆盖范围。不得用该裁剪预览推断地图完整性。后处理生成 median 附近厚度0.1 m的 XY/XZ/YZ 图，每面少于50点可缺席；480像素只是预览参数。无 observed/gradient mask 的 PNG 不能证明未知区处理正确。核验 PNG 解码、尺寸、切片元数据、PLY 数量/有限性和 manifest 实际登记项。

## 恢复 GPU 后按顺序继续

从整合目录执行第一条：

```bash
bash ops/continue-gpu.sh preflight
```

它只做环境检查，不创建任务、不启动算法。当前 2 GiB 模式会明确退出。8 GiB 只是编译保护阈值，不是正式部署容量或算法预算。恢复正常内存后先核实实际 4090 与 cgroup 限制，再准备缺失包（先审查 apt 事务，避免升级既有算法依赖）：

```bash
apt-get -s install --no-install-recommends libgoogle-glog-dev libgflags-dev
# 审查后执行同一 install 命令，去掉 -s。
# 独立工具环境若丢失：
/usr/bin/python3 -m venv /root/autodl-tmp/envs/distance-tools
/root/autodl-tmp/envs/distance-tools/bin/pip install -r ops/distance-tools.requirements.txt
bash ops/distance-env.sh bash backend/scripts/build_esdf.sh --fetch
bash ops/distance-env.sh bash backend/scripts/build_esdf.sh --build
```

编译串行，强制使用系统 Eigen/glog/gflags/Protobuf，避免包装库内部 make -j8 回退。源码有改动或与 lock 不同会停止并保留现场。CMake 本轮做了链接/头路径修复，但没有真实 configure/build，失败时保留 `envs/distance/ws/logs/` 与 `converter-build/CMakeFiles/`；不宣称可直接成功编译。

**在算法契约修复前，只能做独立诊断，不能对外登记真实成功。** 修复后创建小型解析输入，运行候选程序并用同版本 Voxblox 读回检查，`/usr/bin/time -v` 记录耗时/峰值内存；三维负区、未知区、网格半格偏移、权重1/2、空输入、截断、失败返回、最短路径均应覆盖。不要在当前2 GiB模式运行2.5 m波前扩张。

如果先用历史 Surface，来源示例是 `job_1792219486_ec99dd/stage2_surface/runs/20261017_144929_768cd948/`。先运行 `backend/.venv/bin/python backend/scripts/distance_input.py --job-dir jobs/job_1792219486_ec99dd`（只读头，不扫大文件）；复制/抽取经注明的**小样本**到独立诊断目录，不改历史 Job/manifest，不把它说成新 Job 三阶段。真实 map 读回通过后再考虑全量。

正式GPU运行前审查 `ops/platform.local.env`：本轮为了受限平台进程设置的 `OPENBLAS_NUM_THREADS=1` / `OMP_NUM_THREADS=1` 会被子进程继承；恢复正常资源后移除这两条临时工具限制并重启平台，避免限制算法的CPU线程性能（本轮没有运行算法，没有改变质量参数）。

最后恢复正常内存的前端 `npm run typecheck && npm run build`、浏览器检查，并更新依赖状态。创建一个**新 Job**，页面显式选择 Pose→Surface→Distance 与 full，核对 Job 设备/算法参数快照和该数据集已注册的范围；不要编辑历史 requested_stages 或借用历史 Pose/Surface。检查同 Job 新产生的 GLIM轨迹→MrHash输入→voxel_points→Distance manifest，时间先后、运行命令、frame accounting、原生结果/预览/下载、取消/失败/重启恢复。页面支持 full/short 的 Livox 数据集默认 full：Pose处理整包，Surface不设帧上限；short仅将Surface限制在原始第1–100帧。直接API未传run_mode时沿用数据集注册范围，须看Job的run_scope；不得为2 GiB修改质量参数。

日志：`logs/backend.log`、`logs/frontend.log`、Job 每阶段 `run.log/progress.json/result_manifest.json` 及 `stage2_surface/runs/<run_id>`。记录 `nvidia-smi` 采样、cgroup memory.current/events、`/usr/bin/time -v`、阶段开始/结束、退出码与全部固定提交。具体部署、回滚、证据路径见 `ops/INTEGRATION_20261020.md`。
