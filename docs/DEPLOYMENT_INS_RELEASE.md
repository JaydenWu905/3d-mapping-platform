# INS 两阶段已验收版本：统一部署与恢复说明

版本标识 `ins-two-stage-20261015`。本文是当前部署的统一入口，历史安装记录中的“CPU-only / GPU 未验证 / 人工点击待验收”描述仅代表当时现场。完整一键基线为 `job_1792068244_bb9c22`，关联[工程验收报告](job_1792068244_bb9c22-ins-full-one-click-acceptance.md)。本次保存版本只检查、记录和创建本地 Git 提交，不运行 GLIM/MrHash、不安装或重建算法环境。

## 1. 版本和仓库边界

- 平台独立仓库：`/root/autodl-tmp/3d-mapping-platform-deploy`；源基点 `56c448d27a53f389267a2cc099e743051b8f2e7d`。
- MrHash 独立仓库：`/root/autodl-tmp/mrhash`；源基点 `f284cf6cf90d91f9e0be92de8c8c8c02d051bcb0`。
- 两者保存分支：`release/ins-two-stage-20261015`，均有本地标记 `ins-two-stage-20261015`；平台没有把 MrHash 当作已 vendored 的源码或子模块。
- MrHash 部署提交：`23c98bb09eaf1fe06f54153b046b506303ce599d`，其原生依赖快照父提交为 `b08903397621c7cc769809e5b88e5e35aa2cd1a6`。原生快照保存历史 trace/性能改动及 b1_trace.h，目的是保留现有依赖，不是本次新增算法优化。未纳入的 RGB-D/Replica/tau/pose 实验保留在工作区及源码备份中。
- 平台精确提交由本地 tag 指向；备份目录中的 `release-lock.json` 另记两个仓库的最终提交、bundle SHA 和验收配置索引，避免在一个 Git 提交内部循环引用自身 SHA。
- [release-manifest.json](../ops/releases/ins-two-stage-20261015/release-manifest.json) 绑定仓库、MrHash 提交、基线和报告；[acceptance-job-references.json](../ops/releases/ins-two-stage-20261015/acceptance-job-references.json) 保存实际 Job manifest/config 路径和 SHA，未复制 Job 产物到 Git。

## 2. 支持的数据与范围

当前上传 profile 为 `ins_livox_mid360_verified_bag`，只接受已验证的原始 ROS1 bag v2：

- 文件大小 17125894059 字节；SHA-256 `b7a0e7b20e8f447ff6f49be9470b812ded678e28d96f943f7f9b97fd40250c7f`。
- LiDAR：`/livox_mid360/livox/lidar`，rosbags 规范化类型 `livox_ros_driver2/msg/CustomMsg`，1539 条。
- IMU：`/livox_mid360/livox/imu`，规范化类型 `sensor_msgs/msg/Imu`，30770 条。
- 实际上传注册项 `ins_upload_64cf05888616`，源 bag 位于 `uploads/datasets/ins_upload_64cf05888616/source.bag`。原始固定注册项为 `ins_longcorridor01`，参考源路径 `../INS/2024-06-04-16-24-55.bag`。
- Surface profile：`ins_livox_mid360_custom`；位姿 `T_world_lidar`、米、四元数 `qx qy qz qw`。GLIM 原生轨迹按物理 LiDAR sensor/header 时间生成，标准 poses.txt 用 ROS bag record timestamp 作为 MrHash lookup key；关联容差 0.05 秒，最低关联率 98%，不通过复制最近 Pose 填补缺失帧。

| 网页模式 | Pose | Surface |
|---|---|---|
| 完整运行（默认） | 新 GLIM 处理完整序列 | 本 Job 新 Pose → 全 bag，start_frame=1，end_frame=-1 |
| 短段验证 | 仍为完整 GLIM | 原始第 1–100 帧，沿用已验证策略 |

`POST /api/jobs` 的 `run_mode=full|short` 持久化至 Job，Surface 准备核对 mode/scope。旧注册项中的 integration_end_frame=100 保留给短段/旧调用；显式完整模式按新 Job 范围取消限制。算法参数 `n_frames_invalidate_voxels=100` 是体素失效策略，不是处理帧数截止，勿为外观更改它。

只验收这份 INS bag/profile。保留的 Oxford reader/注册功能不构成本轮完整一键验收，RGB-D backend 仍不可运行；不保证任意 bag 兼容。

## 3. 实际环境与代码加载路径

[environment.json](../ops/releases/ins-two-stage-20261015/environment.json) 为只读捕获，包含完整包版本、库 SHA、RPATH、ldd 和工具链线索；下表是摘要。

| 部分 | 实际环境 |
|---|---|
| OS / GPU | Ubuntu 22.04.5，RTX 4090 24564 MiB，驱动 595.71.05 |
| 平台后端 | backend/.venv，Python 3.12.3（底层 Anaconda），FastAPI 0.143.0，uvicorn 0.54.0，NumPy 2.5.4，trimesh 5.1.1，SciPy 1.18.1，fast_simplification 0.2.0 |
| 网页 | Node v24.21.0，npm 11.19.0；完整 npm 解析由 frontend/package-lock.json 保存，React/three/Vite 的直接版本见 frontend-direct-versions.json |
| GLIM / ROS | ROS2 Humble；ros-humble-glim-cuda12.6 和 glim-ros-cuda12.6 均 1.2.2-0jammy；ROS rclpy 为系统包 |
| ROS1→ROS2 bridge | ../envs/glim_bridge，系统 Python 3.10.12，rosbags 0.11.5，NumPy 2.2.6；通过 ROS setup 加入 rclpy，不在平台 venv 混装 ROS |
| MrHash | .pixi/envs/default，Python 3.11.13，torch 2.7.0，rosbags 0.10.10，Open3D 0.18.0，CUDA nvcc 12.8.61；Pixi 0.79.0 |

实际执行路径：

1. FastAPI 进程 cwd 为平台 backend，命令使用 backend/.venv/bin/uvicorn app.main:app；Python executable 的底层文件是 /root/miniconda3/bin/python3.12，但包隔离在 backend/.venv。
2. 前端是本仓库 frontend/node_modules/vite/bin/vite.js，通过 /api 代理到 127.0.0.1:8000，未从另一个平台副本加载代码。
3. GLIM 子进程 source /opt/ros/humble/setup.bash，再将 /usr/local/lib 放在 LD_LIBRARY_PATH 前部、移除 OMP_NUM_THREADS，执行 /opt/ros/humble/lib/glim_ros/glim_rosnode。/usr/local/lib 的 GTSAM 4.3a1 和 gtsam_points 1.2.2 是外部依赖，版本与 SHA 已记录，不能只安装一个同名系统包就假设等价。
4. 平台通过 Pixi 调用 MrHash 仓库 `mrhash/apps/rosbag_runner.py`，其 utils 从同一源码目录加载。原生模块来自 Pixi site-packages 的 `mrhash/src/pygeowrapper.cpython-311-x86_64-linux-gnu.so`，editable finder 的 rebuild 标志为 false；不会因源码变动自动重建。该库 RPATH 指向当前 Pixi 绝对路径，ldd 实际链接该环境的 libtorch、CUDA、OpenCV 等库。
5. 实际扩展 SHA-256：`d4d8da277b29836746eb01c1bc0f7b1d16189071fd2b8f8cbd161f4fd6d89267`。不提交此 .so、build、.pixi 或虚拟环境。

### 原生二进制重现限制

安装扩展时间早于当前 geowrapper.cpp。CMakeCache 的架构值是 52，Ninja 中却记录了另一套 gencode；这些元数据可能来自不同构建时刻。已保存当前原生源码、头文件、子模块/Fetched dependency commit、CMake 选项、Ninja flags、扩展 SHA 和 ldd，但**尚不能证明当前源码精确产生了验收所用二进制**。本次不重建、不替换，不声称干净机器或逐字节复现已验收。

当前机器可继续使用保留的环境与数据恢复代码；迁移要么另行保存完整机器/环境镜像，要么在新环境重建并重新验证。离线迁移还需保存系统包、conda/PyPI/npm 包及外部库的实际可安装介质；Git 和哈希本身不包含这些内容。

## 4. 配置模板和目录布局

预期 workspace：

```
workspace/
  3d-mapping-platform-deploy/    # 此平台
  mrhash/                      # 精确 MrHash 提交及 Pixi 环境
  envs/glim_bridge/             # Python 3.10 bridge venv
  INS/2024-06-04-16-24-55.bag    # 固定注册项，可选；上传路径另见 uploads/
  .pixi/bin/pixi               # 或把 pixi 放入 PATH
```

- `ops/templates/glim-runtime.env.example`：复制到 ops/glim-runtime.env 并调整 workspace、ROS、bridge、GLIM config 和 MRHASH_ROOT。现有 ops/glim-runtime.env 只有机器路径，不含凭据。平台脚本只读取这个文件，不自动加载 .env 或 *.local.env。
- `ops/templates/ins_verified.local.json.example`：固定源注册模板，按实际文件位置修改 root、pose.bag_path、config_path，再保存为 backend/config/datasets/ins_verified.local.json（Git 忽略）。文件 hash/size 和传感器/时间语义不要改成任意 bag 的值冒充已验证 profile。
- 上传通常无需手写注册文件：上传服务从 backend/config/datasets/ins_longcorridor01.json 生成 ins_upload_*.json，此类动态注册项不进 Git。恢复已有上传或 Job 时，必须另外迁移对应注册 JSON、uploads 和数据文件，保持 Job 的 dataset id 可解析。
- GLIM 配置模板保存在 ops/glim_runtime/config（允许注释的 GLIM JSON），适配器逐 Job 复制并覆盖统一话题和无界面设置；保留外参 T_lidar_imu=[0.011,0.02329,-0.04412,0,0,0,1]、acc_scale=9.80665、perpoint_time_scale=1e-9。其原始标定与单位依据待确认。
- MrHash 模板为独立仓库 mrhash/configurations/ins_livox_mid360.cfg，平台只替换输入/输出路径与范围。体素 0.05 m、SDF 截断 0.40 m、最小权重 10、深度 0.2–100 m 等参数与验收一致。保持 MRHASH_B1_TRACE 未设置。
- backend requirements.txt 为依赖声明，release 目录的 platform-python.lock.txt 是当前精确版本冻结；bridge/mrhash-python.lock.txt 是版本清单，**不要把它们当作可直接 pip 安装的完整 ROS/CUDA 环境**。MrHash 恢复以 pyproject.toml + pixi.lock + mrhash-conda-packages.json 为线索；可选验证脚本依赖见 ops/requirements-verification.txt。

## 5. 当前机器服务操作与远程访问

以下启动的是网页/调度服务；只有网页操作运行任务才会启动算法。

```bash
cd /root/autodl-tmp/3d-mapping-platform-deploy
ops/platform.sh status
ops/platform.sh start
# 停服务前确认没有运行中的任务，避免中断任务：
ops/platform.sh stop
# 跟随日志，Ctrl+C 退出跟随：
ops/platform.sh logs
```

脚本记录 .run PID，校验进程 cwd/cmdline，拒绝占用端口，等待 HTTP 就绪。日志在 logs/backend.log、logs/frontend.log；单 Job 算法日志在各 stage/run.log。后端 http://127.0.0.1:8000/api/health，网页 http://127.0.0.1:5173；不开放公网监听。

从个人电脑使用已有 SSH 账户转发（替换占位参数）：

```bash
ssh -N -L 5173:127.0.0.1:5173 -p <SSH_PORT> <SSH_USER>@<SSH_HOST>
```

浏览器打开 http://127.0.0.1:5173/。Vite 已代理 /api，通常无需转发 8000。服务会在重启时把当时 running/queued 的任务标记中断失败，不能依赖重启恢复正在执行的算法。

## 6. 上传 → 完整运行 → 预览/下载

1. 打开 /jobs/new，选择上面校验过的原始 .bag 与 INS profile，点击“上传、预检并自动注册”。支持按服务端 offset 续传，检查完整 hash、话题、数量与消息字段。现有已注册数据集可直接选择。
2. 选择“完整运行”，确认页面说明完整 GLIM→完整 Surface，点击一次“创建并一键运行”。新 Job Pose/Surface 从 waiting 开始，不导入旧轨迹或成功状态。
3. 观察排队与日志：GLIM 启动 ROS bridge，输出本 Job 的 native/index/canonical Pose；通过关联门限后自动准备同 Job Surface 输入并运行 MrHash。若 Pose 失败、取消或 handoff 不兼容，下游不能正常融合，保留日志定位，不盲目重跑。
4. 页面显示全包、选中、关联、实际融合与跳过数。tqdm 计数是成功返回 reader 的融合调用，分母是全包数；100% 为阶段完成，不表示每条消息都有 Pose。完整基线发布 1539 LiDAR/30770 IMU，有效 Pose/实际融合 1527，头 11 帧及尾 1 帧无 Pose，内部漏帧 0。
5. Pose 自动取景并可重置，起终点标记已缩小；黄色辅助线是轨迹切向。Surface 默认中性灰，另有法线方向和 GLB 原始材质模式。原生 Mesh 与 GLB 预览分别登记，原生 PLY、voxel、hash、配置、帧统计和 ledger 可下载。
6. 原生 2389022 面，GLB 按既定 500000 面阈值简化，元数据保留前后面数、bounds、大小和 SHA。简化会改变细小分量与边界，不把预览当作原生几何质量证据。未删碎片、补洞或平滑掩盖问题。
7. 完成状态和 manifest 落盘；刷新/重启服务后仍可查看和下载。验收页面 `/jobs/job_1792068244_bb9c22`；不得删除三份基线来腾空间。

## 7. 资源和已知边界

完整一键基线：Pose 241.5 s，Surface 198.4 s，总体约 459 s；采样显存峰值 20642 MiB，进程树 RSS 合计约 12.03 GiB。1 秒采样不是瞬时峰值，RSS 可重复计入共享页。

必须维持单 GPU 串行：平台以 runtime/locks/gpu_pipeline.lock 串行两阶段及跨 Job，GLIM 还有其共享 dump 锁。外部直接运行脚本不会自动遵守平台锁，不要并发运行。验收实测 queued→运行，GLIM/MrHash 未重叠；当前版本未作多 GPU 或分布式调度验收。

边界：仅此 INS profile 的工程链路已验收；外参和 IMU 单位原始依据、任意 bag 兼容、建图精度、第三模块均未验收。原生碎片与局部几何问题保留，当前 GLB 有 844 个零法线顶点；Pose 流式阶段没有可靠逐帧百分比，最终统计看 bridge/association。Vite 大 chunk 提示仍存在。

## 8. 恢复和迁移（本轮不执行安装/构建）

### 同机恢复源码

先另建目录恢复，不在运行中的目录使用 reset/clean：从备份 Git bundle 克隆两个仓库并 checkout 本地 tag，使用 release-lock.json 核对平台/MrHash 精确提交。MrHash 子模块独立，父仓库 bundle 不打包其仓库对象；备份中另存 submodule bundles，或按固定 Gitlink 从上游获取。源码修改前的 unstaged/staged patch 与必要未跟踪源码另存，可在对应 base HEAD 上的隔离 checkout 中还原历史实验。

代码可以从 Git 恢复；运行环境、数据、动态注册项、Job 和本机库仍需保留或单独迁移。现有 Pixi editable finder、RPATH、venv shebang 绑定旧绝对目录，**不能把换路径后的源码 checkout 当作已迁移的运行环境**。若仅切回原目录的代码且保留原环境和数据，可在轻量检查后恢复服务。

### 新机器准备线索

1. 获取两个精确提交、MrHash 子模块及记录的 fetched dependencies。安装介质应与 environment.json、os-packages.tsv、pixi.lock 相匹配；GLIM Humble CUDA12.6 二进制与外部 /usr/local GTSAM 系列单独处理，不能用 nvidia-smi 的 CUDA 字样代替 nvcc/ABI 检查。
2. 平台用 Python 3.12 建隔离 venv，按冻结版本重建依赖；前端用 package-lock.json 的 npm ci。bridge 用系统 Python 3.10 单独 venv，通过 ROS setup 使用 rclpy。不要在 FastAPI 全局环境 source ROS。
3. MrHash 在新 Pixi 环境按锁文件恢复，明确 Torch_DIR、CUDACXX/CUDAToolkit_ROOT、Python ABI、目标 GPU 架构与 RPATH 后再构建 editable 扩展。当前缓存与 Ninja 不一致，禁止直接照抄架构 52 当作验收标准。历史构建使用 Pixi 的 Torch 安装，源码里的 third_party/libtorch 目录当前不存在。
4. 调整配置模板与绝对路径；另行迁移 bag、动态注册项、三份 Job、uploads、必要运行配置及其 SHA 清单。不要把这些内容放进 Git。
5. 先运行轻量检查与已有产物访问检查，再在独立新任务做经过授权的算法重验收。此步尚未完成，因此本说明提供恢复材料，不宣称新机器已能逐字节再现算法结果。

## 9. 保存内容与推送建议

建议今后推送：平台保存分支及本地 tag，包含已验收源码、测试、依赖、公开配置模板、统一说明与版本/配置指纹；MrHash 应推送到自己有写权限的 fork 的保存分支及 tag，包含原生依赖快照和 INS integration 两笔提交。当前 MrHash origin 是 rvp-group 上游，不假定有推送权限。

不推送：任何 Job、数据集/上传包、环境、node_modules/dist/build、.so、安装/算法日志、密钥、未选入的 RGB-D 和敏感性实验。后者已在现机及源码备份中保存，若日后需要分享应单独审核、另建实验分支。源码备份和完整 bundle 只在本地保存，本轮没有任何远端写入。
