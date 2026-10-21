> **2026-10-21 更新：** GPU恢复后真实构建、小样本数值与既有完整Surface独立验证已完成；正式算法定义、当前三阶段结果与命令见 [本次部署报告](../ops/INTEGRATION_20261021.md) 和 [零面距离场契约](distance-surface-contract-20261021.md)。下文2026-10-20内容保留历史证据，旧“尚未编译/无生产模式”不代表最新状态。

当前构建/验收入口：`bash ops/continue-gpu.sh preflight`、`build`、`native-surface-tests NEW_REPORT_DIR`。正式模式为 `--surface-esdf --input-grid mrhash_integer_centers --input-resolution 0 --source-voxel-size H --voxel_size H`，不能用旧diagnostic冒充。生产就绪绑定真实数值及完整Surface验收证书的转换器/reader SHA；新的完整任务用 `bash ops/continue-gpu.sh acceptance ins_longcorridor01`（该命令会新建并启动，不要重复运行已有验收Job）。

# Distance 部署与验收指南（2026-10-20 第二轮修订）

> 代码已接入；本轮最小源码修复、Python参考与共享C++输入核心检查通过。**完整Voxblox转换器未编译运行，真实ESDF和新Job三阶段未验收。** 当前没有可用的正式生产转换模式。不能只安装依赖或删除gate就标为就绪。

逐项源码位置、触发条件、已证明错误/待定契约/其他配置兼容问题，以及上一轮两处结论更正，见[源码与契约复核](distance-contract-audit-20261020.md)。

## 代码、依赖与隔离

平台main `01fd3fc19fa9e936b792f935c00a7713c5c69d15` 已含PR #8。原转换器是同仓库 `backend/scripts/esdf_cpp/voxel_points_to_esdf.cpp`，原始提交 `c2120cb4cf7be7008cb6d856021e32b3570dd1c8`；不是子模块，也没有另一份必须从作者机器复制的定制源码。

Voxblox固定 `c8066b04075d2fee509de295346b1c0b788c4f38`，catkin及其他依赖的精确提交在 `ops/distance-sources.lock.json`。本机源码 `/root/autodl-tmp/envs/distance/ws/src/`，隔离Python 3.10工具环境 `/root/autodl-tmp/envs/distance-tools/`。catkin-tools 0.9.5等已装；已有Eigen/Protobuf/CMake/g++，缺glog/gflags开发包。没有已验收镜像或转换器二进制。

只构建catkin体系的`voxblox`核心库，不构建voxblox_ros，不需要roscore；锁定catkin来自noetic-devel不代表已安装ROS Noetic。用 `ops/distance-env.sh` 清理子进程环境，不source全局ROS1/ROS2，不污染GLIM Humble、平台或MrHash Pixi。build脚本串行，显式fetch/preflight/build；8 GiB阈值仅作编译保护，不是部署容量。

## 实际输入与本轮修复

输入是同Job Surface manifest声明的非Mock `voxel_points`，world/meter，float32 x/y/z/sdf/weight + uint8 RGBA，binary_little_endian，24字节。Mesh/GLB不能回退成TSDF。

当前MrHash LiDAR reader强制projective_sdf=True：sdf是米制、未归一化的投影距离，传感器侧正；weight>0导出，转换器weight>=2过滤保留原策略。weight=1不是坏原生数据，过滤后不意味着空闲。缺席可能来自未观测、窄带外或清理，不可填零或默认自由空间。

当前INS的sdf_var_threshold=0，固定源码不会启用自适应重分配，h=本Job配置0.05 m。**不再把混合层作为该配置的无条件阻断。** 其他threshold>0/不同分辨率配置需要可靠层级/extent契约，当前明确拒绝。

MrHash原生采样/finest中心为i*h，Voxblox中心为(i+.5)*h。没有`+0.5`不是MrHash导出错误；需要世界坐标不变的插值/重采样，而非固定平移。`distance_input.py`可从当前配置报告finest证据，但一个uniform JSON声明不能把原artifact变成已重采样数据。

已实施的源码修复：

- C++共享输入核心 `voxel_input.h`：格式/字段、空输入、数值/权重、中心一致性校验；驱动检查记录个数、截断/尾随数据、重复目标索引，错误退出，避免last-write-wins。
- 仅接受显式声明、实际几何一致的同分辨率Voxblox中心规范输入；原生整数中心、不同分辨率、粗层、重复体素需要另行定义重采样/聚合，不能硬凑。
- 旧诊断传播改为best距离松弛、出队finalize，修复首次入队锁定；**图最短路仍不是精确欧氏距离，尚未跑完整转换器验证。**
- Voxblox预览改用真正中心，增加浮点输出精度，检查原生层保存bool、PLY写入及目录错误。这不是修改原始MrHash坐标。
- 转换器只允许 `--validate-only` 与 `--legacy-diagnostic`。诊断只能写 `diagnostic-unaccepted.esdf` / `preview/diagnostic-unaccepted.ply`，不生成正式map.esdf或成功manifest。没有隐式生产入口。

仍阻断：世界坐标下的重采样及重复聚合政策、投影TSDF→ESDF定义（fixed band/精确或quasi模式/支持域等）、未知区查询与推断标记政策、完整依赖构建和真实距离场测试。固定Voxblox的EsdfIntegrator示例是候选实现依据，不能直接用默认参数替代这些选择。详细可选方案见复核文档；本轮没有擅自改变距离场定义。

## 本轮验证与未验证边界

- Python参考/输入检查14项通过：斜射平面正负方向、投影与欧氏距离差别、正负索引、中心约定、重复、层级/尺度拒绝、未知、权重和非法数值。
- 小型C++共享输入头测试通过，峰值约119 MiB；**没有链接Voxblox，也没有执行传播/序列化。**
- 完整后端CPU回归195项通过；既有服务不重启，历史数据不改。
- 完整转换器、`verify_esdf_layer`、native测试驱动和真实三阶段均未运行。当前没有用Mock替代native检查；未来native驱动缺少真实ELF二进制会直接失败。
- 有界读取历史PLY的512条记录仅用于契约核对，不是对历史产物执行Distance，也不是新Job联调。

## GPU模式恢复后按顺序执行

当前运行目录 `/root/autodl-tmp/3d-mapping-platform-integrated`。本轮可重跑的轻量入口：

```bash
bash ops/continue-gpu.sh reference-tests
```

1. **恢复资源、预检。** 不自动启动算法：

```bash
bash ops/continue-gpu.sh preflight
```

确认cgroup恢复正常内存、GPU可见且为预期4090。正式运行前移除`ops/platform.local.env`中本轮临时OPENBLAS_NUM_THREADS/OMP_NUM_THREADS限制，并计划重启平台加载新源码/文案；不是在本轮2 GiB环境里做此重启。当前运行服务仍缓存上一版未就绪文案，两版都阻止未验收的真实Distance。

2. **安装缺失依赖并隔离编译。** 先审查事务，不升级已验收算法环境：

```bash
apt-get -s install --no-install-recommends libgoogle-glog-dev libgflags-dev
# 审查后去掉 -s 执行上述安装。
# 工具环境丢失时才重建：
/usr/bin/python3 -m venv /root/autodl-tmp/envs/distance-tools
/root/autodl-tmp/envs/distance-tools/bin/pip install -r ops/distance-tools.requirements.txt
bash ops/distance-env.sh bash backend/scripts/build_esdf.sh --fetch
bash ops/continue-gpu.sh build
```

构建候选为 `envs/distance/converter-build/voxel_points_to_esdf` 和 `verify_esdf_layer`。CMake/新读回工具本轮未完整configure/build；失败保留workspace logs和converter-build/CMakeFiles，不用大规模清理重新开始。锁文件不符会停止，不覆盖现场。

3. **独立第三模块小样本输入与诊断检查。** 自动生成小型合成输入，不读真实大PLY，不写历史Job；报告目录必须是新的：

```bash
bash ops/continue-gpu.sh native-input-tests /root/autodl-tmp/deployment-preservation/gpu-distance-input-01
bash ops/continue-gpu.sh native-diagnostic /root/autodl-tmp/deployment-preservation/gpu-distance-diagnostic-01
```

前者调用实际ELF验证plane input、中心、重复、不同层/分辨率、空/非法/截断等。后者额外用小合成输入执行**未验收旧算法诊断**并用同版本Voxblox读回；`.2 m`传播范围只针对这份诊断fixture，不改变正式建图质量参数。结构读回/输入检查通过仍不能说欧氏符号距离通过。未知扩张和投影种子问题有意保留在显式诊断中，不得把诊断map重命名为正式产物。

4. **完成剩余算法契约后验证真正距离场。** 实施经明确选择的重采样与TSDF→ESDF流程，更新正式CLI及`run_esdf.sh`，再建立同版本native解析平面/斜平面/球测试：比较世界坐标查询的期望距离/符号/误差，已知/未知mask、正负边界、权重与截断、中心及混合配置。必须有真实转换器的距离查询测试；本轮Python参考、输入validator、结构reader均不能替代。只有这些通过后才能据实更新生产就绪gate，不能直接删除理由。

如先使用既有真实Surface，仅选 `job_1792219486_ec99dd` 的 `runs/20261017_144929_768cd948` 作为明确记录来源的独立Distance实验；在独立目录准备经说明的小样本，原Job/原PLY/manifest不改。先只读：

```bash
backend/.venv/bin/python backend/scripts/distance_input.py --job-dir jobs/job_1792219486_ec99dd
```

该实验不证明新Job完整三阶段。

5. **新Job真实Pose→Surface→Distance。** 完成上一步及正常内存前端检查/平台计划重启后，以下命令针对GLIM/Livox已注册数据创建一个新full Job并启动三阶段；当前gate未解除时会停止且不创建Job：

```bash
bash ops/continue-gpu.sh acceptance ins_longcorridor01
```

记录输出NEW_JOB。该命令只是启动入口，不替代最终验收；不要借用历史Pose/Surface，不改历史requested_stages。页面支持full/short的Livox任务full为Pose整包、Surface无帧上限，short仅Surface第1–100帧；直接API不传run_mode则沿用registry范围，核对实际run_scope和参数快照。

6. **原生、预览、下载和资源验收。** 新Job原生map必须由实际同版本reader读取：

```bash
# 将下面路径中的 NEW_JOB 替换为上一步真实输出，H替换为实际目标网格尺寸。
/root/autodl-tmp/envs/distance/converter-build/verify_esdf_layer jobs/NEW_JOB/stage3_esdf/map.esdf H
curl --noproxy '*' -f http://127.0.0.1:8000/api/jobs/NEW_JOB
```

同时做真正的距离/符号/未知样本查询，检查map分辨率、16 voxels/side、非空/有限observed体素；未分配块也是未知，reader的unknown计数只覆盖已分配块。预览PLY应为ASCII x/y/z/distance/RGB且坐标为Voxblox中心，|distance|<=1.5 m只是裁剪预览，不代表全图。PNG须能解码，manifest登记项与实际文件一致，切片不足50点可缺席；图片不证明未知区正确。按真实manifest的artifact_id验证下载、Content-Disposition与页面呈现。

核对同一新Job中真实GLIM轨迹、时间关联、MrHash frame accounting、voxel_points来源及阶段时间先后；取消/失败/超时/重启恢复也要检查。日志在平台logs、各stage/run.log/progress.json/result_manifest.json和Surface runs；保留native测试report.json、workspace构建logs、固定提交/二进制SHA、阶段耗时、cgroup memory.current/events与nvidia-smi显存采样。可安装`time`包后用/usr/bin/time -v采集峰值RSS；本机当前无该工具，不把未采集值写成结果。

部署路径和回滚仍见 `ops/INTEGRATION_20261020.md`。未验证状态始终标为未验证。
