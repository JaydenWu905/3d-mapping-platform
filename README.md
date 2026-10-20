# 三模块三维建图平台

网页创建任务、查看进度与产物；后端按 **Pose → Surface → Distance/ESDF** 调度。当前真实 INS/Livox 链路已接通 Pose（GLIM）和 Surface（MrHash-LiDAR），同一个 Job 会先运行 GLIM、保存新轨迹、按时间关联准备 Surface 输入，再运行 MrHash。main 已接入 Distance 调度和转换器源码；本机尚缺库/转换器编译，且实际 ESDF 与自适应网格契约待修复验收。页面默认真实 Job 请求 Pose、Surface，可显式选三阶段；Distance 未就绪时显示原因并拒绝真实运行。`demo_room` 的三阶段均为演示 Runner；Oxford 路径导入已注册 Pose 后运行 MrHash，不会为 Oxford 启动 GLIM。MrHash RGB-D 接口已登记但运行入口禁用。

## 2026-10-20 本机整合状态

| 层级 | 状态 |
|---|---|
| 最新 main / PR #8 / 新前端代码 | 已接入独立 worktree，未推送 |
| 平台 Python / 前端依赖 | 已就绪；保留原 GLIM/MrHash 环境 |
| Distance 环境 | 固定源码、隔离 catkin 工具已准备；glog/gflags 与 C++ 编译待完成 |
| CPU 检查 | 最终后端195项、前端5个测试文件、51文件语法检查通过；合成预览与Mock取消另有独立记录 |
| 完整前端 typecheck/build | 320 MiB 堆限制下 typecheck 退出；恢复正常内存后执行，未做生产构建 |
| 真实算法 | 本轮未运行 GLIM/MrHash/Distance |
| 新 Job 三阶段真实验收 | 未通过，不能把代码接入或 Mock 测试当作验收 |

当前资源限制是临时无 GPU / 2 GiB，**不是正式部署容量**，未降低算法质量参数。[本次部署与回滚](ops/INTEGRATION_20261020.md)、[Distance 实际契约与后续操作](docs/deploy-distance.md)。GPU 模式恢复后从整合目录执行 `bash ops/continue-gpu.sh preflight`。

第二轮Distance复核已修正“当前混合层/中心缺偏移”的过度判断，并完成输入/队列/输出的最小源码修复。195项后端CPU回归及小型共享输入核心检查通过；完整转换器未编译运行，重采样与距离场/未知区定义仍待确定。见[逐项源码与测试边界](docs/distance-contract-audit-20261020.md)，GPU后使用修订后的 `ops/continue-gpu.sh` 分步继续。

## 当前支持范围

| 入口 | 数据与用途 | 状态 |
|---|---|---|
| `ins_livox_mid360_verified_bag` | 固定 INS 原样本；大小和 SHA-256 均固定 | 真实完整 Pose→Surface 浏览器一键工程验收通过 |
| `ins_livox_mid360_same_rig` | 同一物理 MID-360、IMU、安装、固件和采集配置的新序列 | 上传、流式 CPU 预检、动态注册已实现并经合成 bag 测试；真实新采集序列端到端未验收 |
| 独立设备配置 ID | 自采设备，消息结构仍为 Livox CustomMsg + sensor_msgs/Imu | 可配置话题、帧 ID、标定并运行 CPU 预检；新设备的真实算法结果与精度尚未验收 |

上传入口均只接收单个 **ROS1 bag v2.0 `.bag`**，支持的消息类型为 `livox_ros_driver2/msg/CustomMsg` 与 `sensor_msgs/msg/Imu`。原 INS 两个入口的话题仍为 `/livox_mid360/livox/lidar` 和 `/livox_mid360/livox/imu`；其他自采设备的话题、帧 ID 和标定由独立设备 ID 选择。同消息格式不能证明同设备或同标定。服务器保管设备 profile，不接收用户脚本、路径或算法配置。原 INS 外参和 IMU 单位来自交接配置，**原始依据待确认**。CPU 预检通过只表明输入结构和所选配置符合运行前提，不代表算法成功或精度合格。其他消息格式、ROS2 bag、RGB-D 不在该上传入口。

字段、时间语义、限制、阻断条件和 API 见[新序列上传说明](docs/livox-new-sequence-upload.md)；CPU 测试和真实验收边界见[验证记录](docs/livox-new-sequence-cpu-validation.md)。原固定样本的完整工程验收见[历史报告](docs/job_1792068244_bb9c22-ins-full-one-click-acceptance.md)。该报告只证明原样本，不证明新采集序列。

新增设备或修改硬件参数，请先看[换设备修改指南](docs/换设备修改指南.md)；本机 GLIM 配置路径在 `ops/device_runtime.json` 映射，设备配置位于 `backend/config/upload_devices/<id>.json`。

## 部署与使用

真实链路需要 Linux、Node.js、平台 Python 环境、ROS2 Humble/GLIM、独立的 ROS1 bag 桥接 Python 环境、CUDA/GPU，以及**单独取得并构建**的 MrHash 仓库与 Pixi 环境。仅克隆本平台不能完整运行真实链路。已部署主机的版本、环境和恢复限制见[INS 发布记录](docs/DEPLOYMENT_INS_RELEASE.md)；其中固定样本支持范围是 **2026-10-15 发布 tag 的历史记录**。当前功能分支的新入口以本 README 和[上传说明](docs/livox-new-sequence-upload.md)为准。GLIM/桥接配置说明见[环境文档](ops/GLIM_ENVIRONMENT_SETUP.md)，MrHash 源码、子模块与未解决的扩展来源问题见[外部依赖说明](docs/MRHASH_DEPENDENCY.md)。新机器完整重建尚未验证。

在已具备上述外部依赖的服务器上，从仓库根目录准备平台服务：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && cd ..
test -e ops/glim-runtime.env || cp ops/templates/glim-runtime.env.example ops/glim-runtime.env
test -e ops/device_runtime.json || cp ops/templates/device_runtime.json.example ops/device_runtime.json
# 按本机实际路径编辑上述两个运行配置，并核对 GLIM/bridge/MrHash 安装
ops/platform.sh start
ops/platform.sh status
curl http://127.0.0.1:8000/api/health
```

`ops/glim-runtime.env` 和 `ops/device_runtime.json` 是本机配置，不纳入发布；公开模板不包含可运行环境。`ops/platform.sh` 仅在 `127.0.0.1` 启动后端 8000 和前端 5173。远程访问使用已有 SSH 账户转发：

```bash
ssh -N -L 5173:127.0.0.1:5173 -p <SSH_PORT> <SSH_USER>@<SSH_HOST>
```

然后打开 `http://127.0.0.1:5173/` → **新建任务**：

1. 选择固定样本或同设备新序列 profile，上传 `.bag`；新序列还需确认来源。分块上传支持续传，预检结果显示实际消息数、时间范围和异常原因。已有已注册数据集可直接选择。
2. 预检通过后选择数据集和 **完整运行** 或 **短段验证**，点击 **创建并一键运行**。两种模式均对本次整包新运行 GLIM；完整模式让 Surface 处理本次整包，短段模式只让 Surface 处理原始第 1–100 帧。新序列较长时仍可能受 Pose 1500 秒超时限制。
3. 在 Job 页查看进度、时间关联和融合统计、日志与产物。原生 PLY Mesh 可下载；网页展示的是按面数阈值简化后的 GLB 预览，不能用它替代原生网格做几何质量判断。

部署命令、受控配置、SSH、产物、恢复和已验收资源数据详见[INS 发布记录](docs/DEPLOYMENT_INS_RELEASE.md)。上传 API 和字段见[新序列上传说明](docs/livox-new-sequence-upload.md)。运行数据、上传文件、Job 产物、环境及编译文件均留在服务器，不随源码发布。

## 验收边界

原 INS 样本的完整 GLIM→MrHash 工程运行、页面与原生/预览产物已验收；新序列仅完成代码和 CPU 验证。要验收真实新采集数据，还需有来源明确且能确认同设备、同安装、同采集配置及标定适用性的独立 bag，再单独运行并检查 Pose 时间关联、Surface 帧统计、产物和精度。重传、改名、截取或重打包原样本以及合成 bag 都不能替代该验收。main 新接入的第三模块未在本轮联调验收；任意设备兼容、建图精度和新机器环境重建也未验收。
