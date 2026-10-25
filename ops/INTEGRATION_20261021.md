# GPU 恢复后三模块真实验收（2026-10-21）

本记录接续 `INTEGRATION_20261020.md`，不重做一般性审计。初始工作区干净，HEAD `a272d7e`；实际 `74340a8` 标题为 GPU 预检修订，平台整合还包括 `073efd5`。没有覆盖后续修改、推送或改远端 PR。未发现本仓库或祖先目录适用的 AGENTS.md。

证据总目录：`/root/autodl-tmp/deployment-preservation/20261021-gpu-distance/`。机器日志采用 UTC+08，`*-resource-timeline.jsonl` 采用 UTC，二者相差8小时。

## 环境与版本

- RTX 4090 24564 MiB，驱动595.71.05；开始时GPU空闲，无算法或平台进程。cgroup memory.max=128849018880（120 GiB）；开始磁盘余量约64 GiB。没有升级驱动、CUDA或系统软件。
- 编译依赖及测量工具新增6个包：glog/gflags开发包及运行库、libunwind-dev、time；0升级/0移除。glog0.4.0、gflags2.2.2、Eigen3.4.0、Protobuf3.12.4；完整版本、固定依赖提交及库SHA见 `versions.json`。
- GLIM保持原二进制包 `ros-humble-glim-{ros-,}cuda12.6=1.2.2-0jammy`；ROS2子环境加载后ldd无缺失。桥接envs/glim_bridge导入rosbags成功。
- MrHash保持原Pixi环境/扩展，无重建；原提交23c98bb，既存修改未触碰。实测导入扩展成功，扩展SHA `d4d8da277b29836746eb01c1bc0f7b1d16189071fd2b8f8cbd161f4fd6d89267`。适配器增加 `pixi run --as-is`，禁止运行时重装/解锁依赖，并清除无卡/宿主遗留线程覆盖；质量配置未降低。
- Distance沿用固定Voxblox c8066b0、锁文件源码和隔离distance-tools工具环境；不构建ROS适配包、不source ROS1/ROS2，不改GLIM/MrHash环境。
- 原构建关闭测试时，eigen_checks/CMakeLists.txt无条件catkin_add_gtest，触发CATKIN_ENABLE_TESTING=OFF错误。修复为ON，使用已有gtest，无需修改固定依赖源码。所有锁定源码仍干净。始终catkin -j1 -p1、converter --parallel 1；构建重试1耗时2:38.33，峰值636140 KiB。日志保留初次失败及重试，没有清理证据。
- 转换器：`/root/autodl-tmp/envs/distance/converter-build/voxel_points_to_esdf`，SHA **7f35a2a88721ae97f28594e4525e0007eac299b4a3feba0a19896f7b49603d29**。
- 原生读取器：同目录verify_esdf_layer，SHA **88f23da5bde9be4cb90079d1820aa753c2e327d71ecf613b1067b0c19d6a4700**。保存源码后重编译确认两个SHA不变；ldd全部解析到隔离Voxblox和系统已记录依赖。

## 正式算法与验证

详见 [距离场定义与数值测试](../docs/distance-surface-contract-20261021.md)。正式模式为自定义六四面体TSDF零面重建+BVH精确三角形距离，Voxblox负责真实层格式存储；**不声称运行官方EsdfIntegrator，不是旧Dijkstra诊断**。

源i*h世界格点不平移；目标(i+.5)h中心须八角点均weight>=2。投影sdf只决定零面/符号；幅值来自几何距离，计算半径2.5 m，缺支持或超半径保持未知，不扩张自由空间。相同源索引拒绝。粗层和异分辨率拒绝。原生地图不作预览筛选。

实际ELF输入14项通过；旧诊断可运行/可重载仍只算诊断。正式ELF数值14例在 `surface-native-03/report.json`：三种平面最大误差分别7.20e−8、7.92e−8、1.124e−7 m（固定容限2e−6 m）；球面误差.009556 m，小于预先曲率界.021211 m；正负/零交叉/中心坐标、缺角点、低权重精确支持集合、计算半径、重复/空/非法输入、真实保存失败通过。没有abs抹符号、固定平移、填零或按实测放宽门限。

真实阶段适配器另用明确标为 `SYNTHETIC_runner_*` 的小fixture：正常completed；SaveLayer真正保存失败时返回1、progress=failed且无成功manifest。不是实际Job或三阶段验收。

## 复用既有 Surface 的第三模块独立验证

**此项不是新三阶段。** 来源历史Job job_1792219486_ec99dd、run 20261017_144929_768cd948，完整原生9,617,925点；在证据目录 `real-surface-independent` 处理，历史Job、原PLY及manifest未改。输入PLY/config路径、SHA和准确命令在provenance.json/command.json。历史manifest缺少producer扩展SHA，未虚构历史精确二进制证明。

- C++耗时59.90 s、退出0、峰值1,981,748 KiB，完整time日志保留。
- 低权重972,048；八角点支持中心6,970,446；零面三角形10,145,773；10个支持中心因超2.5 m计算半径保持未知。原生有效6,970,436，负值3,701,338；分配块内未知15,229,884，未分配块也未知。
- 真实reader重载0.05 m/16 voxels-side层，5420块；距离[-2.42853,+2.38255] m；有效中心边界[-4.925,-16.225,-1.475]至[73.825,4.575,6.175] m。reader结构统计不替代此前解析数值测试。
- 按固定stride抽取512个输出中心，重新从全部原生输入找其八角点，全部满足权重及同一线性TSDF符号。`support-sign-check.json`保存结果。三个切片均可解码；同世界坐标叠加原生近零点的位置与走廊对应，overlay PNG保留。
- 预览|d|<=1.5 m，只含6,970,431个点；三个中位切片具体中心/范围在slices_meta.json。白色不能解释为自由空间；完整原生map与预览筛选分别说明。总目录约405 MiB（额外overlay/报告略增）。

## 前端、后端及调度修复

完整typecheck通过；生产build（包含tsc -b）通过；前端5测试文件通过。后端全套195项通过；后续修改相关回归、42项Surface输入检查通过；新增就绪证书谓词测试明确不当作算法验收。详细日志在证据目录。Vite仅有>500kB bundle提示，不是构建失败。

就绪证书绑定转换器及真实reader SHA，单有可执行文件不能就绪；二进制变化会阻断。网页检查发现registry把real_execution固定false，已改为从真实验收gate计算。完整链路标记独立于编译和独立Distance，仅在三阶段最终验收后登记。

实际Playwright/Chromium浏览器检查了新建页、数据集、设备选项、完整/短段范围、两/三阶段选择、运行状态与预览；原始截图和pageerror记录保留。首次网页成功创建三阶段Job后，原前端误用两阶段run-planned接口返回409，**当时未运行任何算法**。修复新建页与continue脚本的三阶段分支为run-all；独立HTTP拦截回归验证路由修复（明确SYNTHETIC_HTTP_INTERCEPT_ONLY，未新建真实Job）。通过网页已有Job的“全部阶段”启动同一个新Job，没有反复重跑前两阶段。

## 新三阶段 Job

新Job：**job_1792547241_905fcb**，来自ins_longcorridor01；full，requested_stages=pose/surface/distance，pose_reuse=null。设备ins_livox_mid360_same_rig v1.0.0，SHA e0c8b8ea2f614072b94f66e208f01a34ba50c26b3ae2c05ee10e697f92367922。新建页请求原文及201/409响应均保留，随后网页run-all响应200。Job/input/ACCEPTANCE_20261021.md明确标记本次验收及启动修复。

初始旧validation_scope字段仍为ins_full_pose_surface（历史profile范围字段），前端已按实际requested_stages明确显示三阶段且不预先宣称验收成功；未为迎合验证篡改已有Job状态。

- GLIM真实完整新运行：254.14 s，1539帧输入，1527有效Pose，轨迹长度129.349 m；匹配率.992203、最大残差0 s，开头11/末尾1/中间0缺帧；无Pose重复复用。原门限.05 s/.98保持，association accepted。Surface接收本Job canonical Pose SHA 4518dab9a97788973730ed0f7a0913f88f7c82e891eeba43eec36cdcbf2df9fc。
- Surface实际配置start_frame=1/end_frame=-1、h=.05、sdf_var_threshold=0、原mesh weight10；TSDF导出与Distance weight2独立。固定INS质量配置未降低。

完整最终统计、下载及浏览器结果见本文件末尾“最终验收结果”；中间阶段完成时未提前标记整体成功。

## 启停与回滚

访问SSH转发后的 `http://127.0.0.1:5173/jobs/job_1792547241_905fcb`；后端保持127.0.0.1:8000。生产构建产物由Vite preview在原5173提供（preview继承现有/api代理）；不是公网托管或自动开机服务。

```bash
cd /root/autodl-tmp/3d-mapping-platform-integrated
bash ops/platform.sh status
# 首先确认没有running/queued/cancelling算法任务；不要中断任务。
bash ops/platform.sh stop
bash ops/platform.sh start
# 日志
bash ops/platform.sh logs
# 回滚源码服务，数据保持共享：先停止新版，再运行旧版
cd /root/autodl-tmp/3d-mapping-platform-deploy
bash ops/platform.sh start
```

切换前确认两端口释放；stop若因正在结束的HTTP/hash请求暂未退出，等待status确认，不强杀其他进程。旧源码worktree、原registry、jobs、uploads、device_runtime及GLIM环境映射均保留。不得两版同时绑定端口。ops/platform.local.env已去除旧256 MiB Node堆/线程限制，并配置本次ESDF_EXECUTABLE/ESDF_ACCEPTANCE_REPORT（机器文件不入Git）。需要重建时先按deploy-distance运行native验收；不手改证书SHA绕过测试。

## 限制

工程链路成功不代表实际场景几何精度、设备标定原始依据、任意bag兼容性或机械臂规划安全验收。输入支持域之外没有自由空间保证；可视化白色不能当可通行。自适应网格尚不支持。前端bundle较大，当前为单机Vite preview+uvicorn/nohup，服务器重启须手动启动；没有升级为独立生产反向代理/进程监督系统。

## 最终验收结果

**新真实三阶段 Job job_1792547241_905fcb 已完成并通过本次工程链路验收。** 原始5个历史Job的API摘要（含全部阶段状态）逐项保持不变；仅增加这1个真实Job。三阶段没有重跑，也没有历史Pose/Surface/ESDF复用；唯一启动重试是创建后的run-planned 409→同Job run-all 200，算法尚未启动时完成修复。

| 阶段 | 原生/manifest耗时 | 平台阶段计时 | 最终结果 |
|---|---:|---:|---|
| Pose | 254.14 s | 255.2 s | GLIM新轨迹1527条，全包1539帧，关联99.2203%，缺12（首11/尾1），中间0；轨迹约129.349 m |
| Surface | 206.86 s | 226.5 s（含输入验证等） | run 20261021_095321_6949ff94，选中1539/关联1527/融合1527/缺Pose跳过12；无越界、非法、空消息跳过及计算错误 |
| Distance | 67.69 s（整个适配器） | 68.1 s | 真实C++计算60.88 s，退出0，峰值RSS1,983,296 KiB；原生读取、后处理完成后才登记成功 |

Surface完整原生Mesh：3,178,427 vertices、2,393,414 faces、148,971,022 bytes；新voxel_points **9,639,417** 点、231,346,251 bytes。GLB仅为499,999 faces的QEM预览，原生Mesh可下载，页面明确说明预览简化的差别。Surface/input/surface_input_manifest.json 的trajectory SHA与本Job新Pose完全一致；raw/frame_accounting.json及逐帧ledger可下载。

Distance源SHA：**3ff2dd060b669f805ed1dd78c154b42810fc1dd244a7060d4eb58dead4e54460**，路径位于上述同Job/同run的raw/voxel_points_20261021_095323.ply；配置SHA 56b6b9599bf14c730b1362a60bf2301b0901169e22d3196d07d3b807ac12fe08。二进制SHA与独立数值/既有Surface验收完全匹配。provenance中的旧grid_ready/mapping_blocker字段指旧canonical-center直接导入契约；本次正式路径使用明确的surface_esdf_supported及--surface-esdf，并由完整原生输入检查实际格点/重复/权重，未绕过旧诊断gate。

Distance结果：

- h=.05 m、16 voxels/side、5401 blocks；支持中心6,973,663，**有效6,973,652**，负3,706,248；11个超计算半径保持未知。分配块内未知15,148,844，未分配块也未知。
- 有效距离[-2.41603,+2.39887] m，中心范围[-4.925,-16.175,-1.575]至[73.875,4.625,5.675] m。真实同版本reader重载成功；小样本解析数值验收与结构验收分别保留。
- 预览6,973,649点；三张480×480 PNG，世界切片中心Z=.975、Y=−5.275、X=28.325 m，半厚.1 m；固定红−1.5/紫0/蓝+1.5 m，白色无有效预览采样。新Job另按固定stride复核513个中心的全部角点权重和符号，全部通过，并保留源近零点世界坐标叠加图。
- map.esdf **116,616,855 bytes**，SHA **9dddbe8f759f9963397a0661a11b4716b2a5d1aad962bcd3bfcb4ed0f26b4114**。
- 正式产物：`jobs/job_1792547241_905fcb/stage3_esdf/`；原生、provenance、conversion、native-readback及slices_meta均有登记下载，preview单独登记。

`artifact-acceptance.json`：逐项通过前端原端口API代理读取23个登记下载/预览，其中17个下载；全部HTTP200、完整字节数及SHA匹配，Content-Disposition正确；PNG解码、JSON解析、GLB magic通过。所有阶段日志接口返回200。真实Playwright另点击网页下载map.esdf，保存文件的完整SHA再次一致，不仅检查HTTP头。

生产前端实际使用dist/assets静态构建，仍在5173端口；backend8000不变。Playwright真实查看了Pose轨迹、Surface模型、三方向ESDF切片、任务状态/耗时、设备选项与三阶段选择、下载，pageerror/requestfailed均为空。服务器原缺中文字体导致截图方框，已仅新增fonts-noto-cjk（0升级），重启浏览器后中文截图正常；没有改动驱动/算法环境。截图为 `browser-final-{pose,surface,distance-*}.png`，下载和新建页证据见browser-download-and-new.json（该次仅检查选择，不再创建Job）。Distance完成卡片按原生metrics显示有效体素数和分辨率，不再显示“未上报进度”；切片提示与3D交互提示分别显示。

资源timeline37次、15秒采样：cgroup采样最大**32.568 GiB**，GPU采样最大**20,642 MiB**；此为采样最大观测值，不冒充连续峰值或单进程RSS。cgroup max/oom/oom_kill全为0。完整资源/日志、来源与时间顺序记录保留；没有在中间阶段将整体Job标为completed（timeline检查通过）。最终GPU空闲，平台继续运行；磁盘仍约63 GiB余量。

最终全套后端**201项通过**（13.884 s）；后续registry动态标记相关11项及运行API验证通过；前端最终生产build/类型检查与5测试文件通过。就绪证书回归曾发现“同长度改写并保留mtime，在粗粒度ctime下命中二进制hash缓存”的具体问题，已移除小二进制的stat缓存，改为每次直接hash；原失败日志保留，修复后回归通过，不靠sleep或修改用例放宽。原Surface完成日志存在宿主OMP_NUM_THREADS=0的非致命打包警告，算法子进程本次已清除该覆盖；已进一步在Surface shell入口清除，使后续打包也不再继承此值，无需重跑已通过的建图。

验收证书acceptance.json现登记真实三阶段Job与证据；API返回real_execution=true、cpu_checked=true、full_chain_accepted=true、无unavailable_reason。算法仍以experimental标记其适用范围，不将这一次INS工程验收泛化为所有数据/精度/安全认证。

本地已保存构建修复d6ac47b、正式算法290cf62、原环境运行保护10a5b46、三阶段启动修复a8633fa，以及后续最终部署/验收提交（准确HEAD见证据versions.json与git log）。没有推送、改远端PR、清理历史Job或重建GLIM/MrHash环境。
