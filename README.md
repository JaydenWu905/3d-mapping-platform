# 三阶段三维建图平台

网页创建任务、查看逐阶段进度、日志和预览；后端运行 **Pose (GLIM) → Surface (MrHash LiDAR) → Distance (零面几何距离，Voxblox ESDF 存储)**。完整工程验收仅覆盖固定 INS 室内走廊 ROS1 bag 与其 MID-360/IMU 配置：2026-10-21 新 Job `job_1792547241_905fcb` 从原始 bag 新运行三个阶段，原生 ESDF 读回、下载及浏览器预览通过。[真实验收及资源记录](ops/INTEGRATION_20261021.md)、[距离场定义](docs/distance-surface-contract-20261021.md)。精度、安全及其他场景没有据此验收。

同一物理设备的新 Livox 序列、其他设备的真实算法结果、ROS2 bag、不同消息格式、RGB-D、自适应网格和新机器完整三阶段重建均未验收。上传入口支持单个 ROS1 bag v2.0，LiDAR 为 `livox_ros_driver2/msg/CustomMsg`，IMU 为 `sensor_msgs/msg/Imu`。[设备配置与消息适配](docs/换设备修改指南.md)。仅更换同格式设备的话题、frame、标定、IMU 单位、时间配置，可新建设备 profile 并核查 GLIM 配置；其他消息结构需要修改 bag 预检、桥接和 MrHash reader。CPU 预检不代表真实算法验收。

## 新成员最快看到相同页面

在 Ubuntu 22.04、Python 3.12、Node 24（本机为 24.21.0）上，从本 PR 的**明确提交 SHA** 检出；合并后可用 main 对应提交。请勿把随时间变化的分支名当成固定版本。

```bash
git clone https://github.com/JaydenWu905/3d-mapping-platform.git
cd 3d-mapping-platform
git fetch origin release/three-stage-20261025
git checkout <PR中报告的完整平台提交SHA>
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
cp ops/templates/glim-runtime.env.example ops/glim-runtime.env
cp ops/templates/device_runtime.json.example ops/device_runtime.json
# 无 GPU 的页面演示只需将模板中的路径按本机目录填写；真实运行须完成下文安装。
bash ops/platform.sh start
curl --noproxy '*' -f http://127.0.0.1:8000/api/health
```

打开 `http://127.0.0.1:5173/`。后端首次启动会从仓库内 `demo_jobs/demo_room` 导入轻量的完成任务 `demo`，包含三阶段预览；**它是模拟样例，不是真实 GLIM/MrHash/Distance 输出**。新克隆没有历史 Job 是正常的。可在新建页选择演示数据运行 Mock 任务；真实 INS bag 必须单独取得并导入。服务仅监听本机，远程用 SSH 转发 5173 端口。`ops/platform.sh status` 检查状态；前端使用已构建的 Vite preview。

## 真实三阶段部署

[完整可重建步骤与检查脚本](docs/RELEASE_DEPLOYMENT.md)给出 ROS2 Humble、GLIM 1.2.2 CUDA 12.6、Python 桥接、MrHash Pixi、Voxblox 固定源码、构建、配置和 GPU 预检。只克隆平台**不足以**运行真实链路：还需可取得的 MrHash 修改提交、原始 bag、系统/算法环境及新机器原生验收。部署脚本不会把本机编译产物打包到 Git。GPU 和足够内存用于真实 GLIM/MrHash；Distance 构建和真实运行也按 GPU 模式预检。历史 2 GiB 内存限制只属于无卡模式，不是 GPU 部署规格。原机三阶段资源采样最大 32.568 GiB RAM、20,642 MiB GPU 显存。

有数据与依赖后，在 `/jobs/new` 选对应已预检的数据集、设备 profile、`Pose + Surface + Distance` 和完整运行，再点击创建并一键运行。短段模式仍对整包新运行 Pose，但 Surface 仅取第 1–100 帧。下载的原生 PLY/ESDF 与网页简化预览不同。新机器须用**独立新 Job**验证，不能用演示 Job、Mock 或复制历史产物代替。[数据单独交付清单](docs/RELEASE_DEPLOYMENT.md#数据单独交付)。

源码、演示样例和用户可修改的 profile 模板随仓库发布；bag、上传、历史 Job、虚拟环境、node_modules、编译产物、日志及本机环境文件不发布。
