# 2026-10-25 发布候选验证与阻断

本记录对应基于远端 main `01fd3fc19fa9e936b792f935c00a7713c5c69d15` 的 `release/three-stage-20261025`；准备/测试时的平台候选提交 `6dd7b2477a4bd7db12666084ae8e6a8464e49d0a`，最终文档提交见 `git log`。原运行目录是 `integrate/three-modules-20261020` / `498b8604f9976dab2cd25b1fcaead1e3825effc6`，带34个修改和15个未跟踪功能文件；用独立 worktree 复制有效源码，原目录未 reset/clean。原平台状态为 stale PID 文件、127.0.0.1:8000 无响应；没有发现正在运行的算法 Job。RTX 4090 24564 MiB、驱动595.71.05、cgroup上限120 GiB。

## 隔离验证

- 从本地候选提交做 `git clone --no-hardlinks --branch release/three-stage-20261025` 到独立目录；初始无 `jobs/`、`.venv/`、`node_modules/`。`python3.12 -m venv backend/.venv` 和 `pip install -r backend/requirements.txt` 完成；Python 3.12.3。`npm ci && npm run build` 完成，Node 24.21.0/npm 11.19.0；9个前端测试文件通过。Vite 提示 bundle 超过500 kB；npm 审计报告3个中危、2个高危，未在此擅自升级前端依赖。
- 首次直接运行后端测试失败：11项与缺少 `ops/device_runtime.json` 有关。从模板复制并按隔离目录调整 `ops/device_runtime.json`、`ops/glim-runtime.env` 后，`PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -q` **219项通过**。因此 README 中的配置复制是必要前提。
- 隔离服务 `ops/platform.sh start`：health 200，前端 `/`、`/jobs/new`、旧 `/jobs/demo` 与新 Job 路径 200；首次启动生成轻量 `jobs/demo`，无历史 Job 是正常情况。旧 demo 与新建名为 `Fresh clone demo` 的 `job_1792892804_5a2b20` 均为三阶段 Mock completed；每阶段登记预览的 API 读取均 200。这验证页面服务路由、Job 创建/命名、旧结构和演示预览的链路，**未进行独立 Chromium 像素/交互验收**。完成后只停止该隔离服务，原机历史 Job 未触碰。
- `ops/continue-gpu.sh preflight` 通过 GPU、内存及已装系统库检查，但 Distance gate 正确报告本新克隆缺转换器/验收证书。固定锁源9个本地仓库均核对 HEAD 与干净状态。全新 GitHub 抓取 Voxblox 在当前网络长期无进度而终止；为验证构建，改从原机独立固定 Git 仓库**本地克隆**到隔离位置。首次 catkin 构建因 GitHub gflags v2.2.1 归档 HTTPS 连接超时；按网络权限流程重试后，隔离 Voxblox/转换器/reader 构建成功。因此**远端全新抓取尚未验收**，本地固定源码构建已验收。
- 隔离 ELF SHA-256：转换器 `3e139a83bb5465100a188438d582f6756f787e7a0508422d6ab58b8ad53c53aa`；reader `75eda8fa785ac322beab03d691611059c83067dab76ff4f90036fd49cd7d38c1`。真实 ELF 数值、符号、unknown、失败输入等14例通过（`native-report` 位于隔离目录，不入 Git）。这两个 SHA 不同于历史二进制，不能复用历史就绪证书。
- 用新 ELF 在独立输出目录、只读输入下处理历史已验收 Surface PLY：输入231,346,251字节/SHA `3ff2dd060b669f805ed1dd78c154b42810fc1dd244a7060d4eb58dead4e54460`；原生输出116,616,855字节/SHA `9dddbe8f759f9963397a0661a11b4716b2a5d1aad962bcd3bfcb4ed0f26b4114`，与2026-10-21原机结果完全一致。同版本 reader：5401块、有效6,973,652、负3,706,248、已分配块内未知15,148,844。该检查复用历史 Surface，不是新三阶段 Job。
- **新机器真实 Pose→Surface→Distance 未验收**：MrHash 修改提交只在本机，公开引用未推送；现有 Pixi 扩展虽能定位并核对 SHA，但其对应当前源码的可重建性未证明。不能以 Mock/历史 PLY/原机旧 Job 代替此项。

## 待发布文件扫描

相对 `origin/main` 的118个变更文件：`git diff --check` 通过。全体 Git 跟踪路径检查无 `.bag`、`.so`、`.env`、Job、上传、node_modules、虚拟环境、dist/build、日志或缓存；`demo_jobs/demo_room` 约632 KiB，是明确标记的 Mock 资产。变更后的现存114个文件逐一扫描结果：凭据/私钥/常见 token 模式 **0**，邮箱模式 **1**（仅本报告中的用户指定提交作者），单文件大于1 MiB **0**；Unix 绝对路径模式58处、分布24个文件，均为脚本 shebang/`/usr/bin` 等系统命令或历史验收文档的本机证据位置。新配置模板使用占位路径，历史路径并非运行默认值或秘密；若迁移机器需按 README 改写。Git 提交作者邮箱 `2078425168@qq.com` 是用户指定的身份，本报告如实引用。未跟踪的当前运行目录文件仍留原处，未提交运行资产。

## 发布阻断与后续

`gh` 未安装；GitHub HTTPS push/dry-run 返回 `could not read Username`，直接 SSH 握手返回 `Permission denied (publickey)`。因此当次无法推送平台分支及计划的 `dependency/mrhash-ins-20261025` 引用，PR 也无法创建。**这两个引用在远端不存在，不能给出真实 PR 编号或声称组员已可克隆完整链路。** 有 GitHub 写入凭据后，先把 MrHash `23c98bb09eaf1fe06f54153b046b506303ce599d` 推到独立依赖引用并从远端新克隆/初始化子模块；再推平台分支、打开面向 main 的 PR。重新编译 MrHash 原生扩展，检查实际加载 SHA；以独立新 Job 和数据所有者提供的 bag 验收真实三阶段，形成新机器自己的 Distance 就绪证书。原始 bag 和历史产物单独按 [交付清单](RELEASE_DEPLOYMENT.md#数据单独交付) 处理。
