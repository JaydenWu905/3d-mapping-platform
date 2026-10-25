# MrHash 外部依赖与取得状态

本平台没有 vendoring MrHash，也没有把它声明为平台子模块。真实 Surface 运行由 `MRHASH_ROOT` 指向单独的源码仓库，经 Pixi 调用 `mrhash/apps/rosbag_runner.py`；实际加载的原生扩展位于该仓库 Pixi 环境的 site-packages。平台仓库、平台 `requirements.txt` 和前端 `package-lock.json` 均不能替代它。

## 本机验收所用源码

- 本机路径：`/root/autodl-tmp/mrhash`；上游 `https://github.com/rvp-group/mrhash.git`；基点 `f284cf6cf90d91f9e0be92de8c8c8c02d051bcb0`。
- 保存分支/tag：`release/ins-two-stage-20261015` / `ins-two-stage-20261015`，提交 `23c98bb09eaf1fe06f54153b046b506303ce599d`；父提交 `b08903397621c7cc769809e5b88e5e35aa2cd1a6` 保存继承的原生依赖源码。部署修改包括 Livox `CustomMsg` reader、bag record 时间索引、融合计数/ledger、`ins_livox_mid360.cfg` 和子模块 HTTPS URL；父提交还有 native 源码改动。平台引用的 reader 和配置都在该提交中。
- MrHash 的 `args`、`json`、`tinyply` 是**它自己的子模块**，父仓库克隆后须按 Gitlink 初始化。固定提交和环境指纹见[发布 manifest](../ops/releases/ins-two-stage-20261015/release-manifest.json)与[环境记录](../ops/releases/ins-two-stage-20261015/environment.json)。MrHash 自身还需 `pyproject.toml`、`pixi.lock`、CUDA/Torch 及系统库。

截至本功能分支整理时，本机 MrHash 只有 `rvp-group` 上游 `origin`，**没有配置自有 fork，也未核实这些本地保存提交可从远端取得**。因此当前不能把 `git clone` 上游加 checkout 上述提交写成可靠的新机器恢复步骤。发布前应由仓库所有者提供有写权限的 fork 或可持续取得的源码地址，单独发布该 MrHash 保存分支/tag，并确认三个子模块的固定 Gitlink 可取得。平台 PR 可以先审查，但真实运行依赖仍是未发布的外部源码。

本机验收使用的 `pygeowrapper.cpython-311-x86_64-linux-gnu.so` SHA-256 为 `d4d8da277b29836746eb01c1bc0f7b1d16189071fd2b8f8cbd161f4fd6d89267`。其构建时间早于当前 `geowrapper.cpp`，现有 CMake/Ninja 元数据也不完全一致；**尚未证明保存源码能逐字节生成已验收扩展**。不要把 `.pixi`、build、`.so` 或整套环境放进平台仓库。新机器须独立重建并重新验收，细节见[恢复说明](DEPLOYMENT_INS_RELEASE.md#8-恢复和迁移本轮不执行安装构建)。

本机 MrHash 工作区另有未提交的 RGB-D、实验配置与 profiler 文件；这些不属于已验收 LiDAR 发布内容，不能混入上述提交。

## 2026-10-25 发布候选更新

计划把上述两个独立提交保留在平台目标仓库的 `dependency/mrhash-ins-20261025` 引用，以便审查并从可访问 Git 地址检出；这不是把 MrHash 二进制塞入平台源码。当前机器 GitHub HTTPS 没有写入凭据、SSH publickey 被拒，实际推送失败；该引用**尚未发布**。新机器重新构建和原生扩展来源验证仍是完整真实链路的阻断。见 [本轮验证](RELEASE_VALIDATION_20261025.md)。
