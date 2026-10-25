> GPU恢复后的接续验证见 [2026-10-21报告](INTEGRATION_20261021.md)。本文件保留前两轮历史状态；最新真实算法定义见 ../docs/distance-surface-contract-20261021.md。

# 本机三模块整合与部署记录（2026-10-20）

> 第二轮源码复核已更正上一轮关于“混合层”和“没有半格偏移”的判断，见[逐项审计](../docs/distance-contract-audit-20261020.md)。当前INS配置禁用自适应降层，MrHash整数中心约定本身没有错；仍缺与Voxblox中心间的重采样及ESDF/未知区政策。以下原验收记录保留历史语境，以本文件末尾第二轮状态为准。

## 版本与取舍

- main：`01fd3fc19fa9e936b792f935c00a7713c5c69d15`（2026-10-19 合并 PR #8）。
- PR #8 head：`c2120cb4cf7be7008cb6d856021e32b3570dd1c8`，定制 C++ 转换器/构建脚本/交接文档；已在 main。
- PR #4 head：`eae2b9b568b5ba334c810abd9548c2522c49323c`，Distance 调度；已在 main。
- PR #7 head：`64d9570179c6c05d27fbd16c0832b0f24497032c`，设备 profile、Job 设备和有效算法参数快照、真实 Pose 发布进度；已在 main。
- PR #6 head：`e013a8862458def9ab309b4905bd3a418b8e79ef`，真实上传/两阶段；已在 main。
- 新前端 Minimal UI 与 scanner 等修复直接在 main，最新前端修复 `b78097f5ebbe88524f0c70257b86295464359553`。
- GitHub API 检查：无开放 PR；不需要挑选未合并 PR。未合并/推送/创建任何远端 PR。
- 已对旧部署**实际文件内容**与 PR #7 比较：修改/未跟踪源码均已覆盖；余下三处是旧版禁用 Distance 的逻辑、缺 Distance timeout 和等价 Python 字典语法。保留 main 的第三模块调度和1200秒超时；未将旧限制重新贴回。上传、GLIM、设备快照、进度和可视化均保留最新实现。未直接套用旧 PR4 候选目录。
- 本机 MrHash `23c98bb09eaf1fe06f54153b046b506303ce599d`；有既存 RGB-D/实验文件修改，未触碰。当前 LiDAR reader/INS配置在该仓库受版本控制。平台仍使用原 Pixi 环境；本轮未运行它。
- GLIM 是已安装二进制，**不能编造源码提交**：`ros-humble-glim-{ros-,}cuda12.6=1.2.2-0jammy`，GTSAM 4.3.0、gtsam_points 1.2.2，ROS2 Humble。详情见原 `GLIM_ENVIRONMENT_SETUP.md`。
- Voxblox `c8066b04075d2fee509de295346b1c0b788c4f38`、catkin `af1cdf271b11b8d55cf66b2ea91a8a30614ddaef` 及其他核心依赖完整 SHA 见 `ops/distance-sources.lock.json`；本轮仅固定并取源码，未编译验收。

整合分支 `integrate/three-modules-20261020`；worktree/实际运行目录 `/root/autodl-tmp/3d-mapping-platform-integrated`。本地整合提交可用 `git log -1` 精确查询；不推送。

## 保护与路径映射

初始旧部署：`/root/autodl-tmp/3d-mapping-platform-deploy`，分支 `feature/device-profiles`，HEAD `e013a8862458def9ab309b4905bd3a418b8e79ef`，有25个受版本控制文件修改与设备/前端等未跟踪源码，无暂存修改。未发现适用 AGENTS.md（检查根/祖先目录和仓库文件）；无平台服务或算法任务在运行，原 PID 文件过期。

完整本轮证据：`/root/autodl-tmp/deployment-preservation/20261020-integration/`：`local.patch`（包含二进制差异）、`untracked-source.tar.gz`、`status.txt`、`head.txt`、`worktrees.txt`、Job初始元数据，以及 API/安装/检查日志。旧 worktree 未切分支、未清理、未覆盖，恢复时无需重新贴补丁。未使用 reset --hard/git clean。

新 worktree 的 `jobs`、`uploads`、`backend/.venv` 是指向旧部署的链接；`ops/glim-runtime.env`、`ops/device_runtime.json` 也引用原文件。新源码的 GLIM 配置与版本化设备文件保持 main，机器映射仍指向已验收的旧部署实际配置。

`ops/platform.local.env` 设置 `PLATFORM_DATASETS_CONFIG_DIR` 为**原 registry 目录**，既保留全部注册，也确保后续上传仍写同一 registry。路径解析的 workspace 仍是 `/root/autodl-tmp`；没有复制大数据/覆盖 registry。不能脱离该 local.env 用裸 uvicorn 启动，否则会看到默认 registry；应使用平台脚本。

## 本轮行为与资源

cgroup memory.max=2147483648，host free 显示约1 TiB不代表容器可用；初始磁盘65 GiB余量，无 swap。无 GPU 模式；未调用 GLIM/MrHash/Distance 算法，未修改质量参数、CUDA、驱动、全局 ROS 或 swap。

本轮依次执行平台准备、测试、前端依赖安装与检查。Node工具限制堆，esbuild限制 Go内存/并行，BLAS单线程，仅限制平台工具资源，不改变算法参数。完整 typecheck 在320 MiB堆上限退出134；未继续抬高内存重试，未执行生产build/大型C++/CUDA/镜像构建。cgroup未发生OOM/OOM kill；max计数上升代表触及内存回收上限，不代表正式容量已足够。

新增输入契约检查、就绪原因、前端阶段选择/默认两阶段、共享registry配置、固定源码构建和独立工具封装。第三模块真实运行同时被创建任务和阶段启动、shell入口阻断；演示仍明确为mock，不回退历史产物。

还修复数据集列表的同步大文件hash阻塞：列表校验在线程执行，校验串行；同一路径的stat版本只hash一次，文件inode/大小/mtime/ctime改变会重新hash，registry或输入文件变化会使校验缓存失效。仍做首次完整SHA，不以文件存在/历史结果替代完整性校验。首次预热仍可能耗时数分钟；健康接口不再随之阻塞。

## 验证边界

- 最终全部186个后端CPU测试通过（包括5个Distance合成契约测试与3个hash缓存测试），测试替身仅用于接口/队列/失败处理。
- 最终全套已包含hash缓存修复；新写入文件两秒内绕过缓存，防止粗粒度时间戳漏掉同长度改写。前端5个测试文件通过，51个源码文件轻量语法转换通过。
- shell语法、平台Python依赖导入、独立catkin工具导入/版本、构建前检通过；2 GiB编译保护/GPU预检能正确拒绝当前模式。
- 平台健康、前端新建页与详情页/模块转换、Vite API代理、设备profile、历史Job列表已返回200；原生Mesh下载与GLB预览返回200（只读取头部，不重传大产物）。完整浏览器视觉交互、语义typecheck/生产build未完成。
- 历史 `job_1792219486_ec99dd` 的 Surface 只做头部/配置只读检查：9617925点、finest virtual_size=0.05 m、缺显式均匀网格元数据；没有转换，没有扫描/处理全点云，没有把历史Job当作新三阶段验收。
- 当前没有真实Distance成功或新Job完整三阶段验收；恢复GPU后仍需解决转换器语义和分辨率/坐标契约，见 `docs/deploy-distance.md`。依赖安装或编译成功不足以解除该阻断。

API/数据集预热和最终验证结果详见证据目录及本文件末尾补充。

## 访问与回滚

运行端口保持后端 `127.0.0.1:8000`、前端 `127.0.0.1:5173`。SSH转发5173后访问 `http://127.0.0.1:5173/jobs/new`，任务列表 `/jobs`。不直接暴露公网端口。

```bash
cd /root/autodl-tmp/3d-mapping-platform-integrated
bash ops/platform.sh status
# 无算法任务运行时回滚：
bash ops/platform.sh stop
cd /root/autodl-tmp/3d-mapping-platform-deploy
bash ops/platform.sh start
```

旧部署保留原依赖、源码修改、Job和上传数据；两者共享数据，禁止同时绑定原端口，切换前检查无running/queued/cancelling任务。需要再切回新版时先停旧服务，再从整合目录start。服务以nohup方式运行，不保证服务器重启后自动启动。

## GPU 模式下一条命令

```bash
cd /root/autodl-tmp/3d-mapping-platform-integrated
bash ops/continue-gpu.sh preflight
```

然后按 `docs/deploy-distance.md` 顺序：缺依赖审查安装→隔离catkin串行编译→修复并验证网格/符号/未知区/最短距离→第三模块小样本读回→正常内存前端构建与浏览器→**新Job**真实Pose→Surface→Distance→原生结果/预览/下载与资源/失败记录。详细日志、产物与读回要求均在该文档，尚未验证的步骤不能改写为已通过。

## 最终补充

最终186项后端CPU回归通过，耗时17.718秒。在线额外创建了一个明确的 `demo_room` **Mock测试Job**，验证Pose启动→取消→cancelled后删除该测试Job；原5个Job集合与元数据保持不变。真实三阶段创建接口返回422，并包含可执行程序缺失/契约原因，没有创建真实任务、没有调用算法。

另以独立1000点**合成ASCII预览输入**只运行Python后处理，生成并解码3张64×64 PNG。该测试没有执行C++、没有生成或验证map.esdf，不是ESDF验收。历史Pose的 `trajectory_model` 预览、`registered_trajectory` 与 `glim_native_trajectory` 下载也均200。首次探测错误的 `trajectory` ID返回404，随后按真实manifest的ID核验通过，没有修改manifest来迎合探测。

最终代码已重新加载到平台服务；数据集校验缓存会随进程重启重建，首轮完整SHA校验需要数分钟。后台预热期间health仍可响应。最终数据集可用性、计时和运行代码标记见 `datasets-final.json`，稳定后再查列表无需重新读取大bag。完整浏览器交互/视觉验收仍未做，不能将HTTP检查和源码测试描述为浏览器验收。


## 第二轮：源码与契约最小修复

已修复严格输入校验、重复目标索引拒绝、图最短路松弛、Voxblox预览中心、保存失败检查；无默认生产转换入口，旧算法只以未验收diagnostic命名输出。当前固定INS源码路径threshold=0保持finest，不再无条件声称自适应混合。MrHash i*h是其原生中心/采样约定，不做固定平移。

本轮Python参考/输入14项、全后端195项通过；仅共享C++输入头的小程序编译/执行通过（峰值121692 KiB），完整Voxblox转换器和新结构reader均未编译运行。所有证明位置、触发条件、剩余设计方案与native检查边界见`docs/distance-contract-audit-20261020.md`。证据存`/root/autodl-tmp/deployment-preservation/20261020-distance-contract/`。

`continue-gpu.sh`新增reference-tests、build、native-input-tests、native-diagnostic、acceptance入口；后四类按资源和真实依赖/gate检查。详细顺序见修订后的`docs/deploy-distance.md`。真实三阶段仍阻断，不能直接删除gate后启动。

既有后端9958/前端9992保持运行，未重启、未改变历史数据和算法环境。页面当前缓存上次版本的未就绪原因；本轮源码/新说明将在GPU模式的计划服务重启后加载。没有为了更新阻断文案牺牲已预热的Pose→Surface服务。
