# Distance 源码与契约复核（第二轮，2026-10-20）

本轮只做源码修复、合成参考检查和小型共享输入核心测试。**完整 Voxblox 转换器没有编译或运行，真实 ESDF 与完整三阶段均未验收。** 不改历史 Job、原始 PLY、MrHash/GLIM 环境或质量参数，不推送。

## 固定证据与上一轮结论修正

- 原始转换器：本平台 PR #8 `c2120cb4cf7be7008cb6d856021e32b3570dd1c8` 的 `backend/scripts/esdf_cpp/voxel_points_to_esdf.cpp`。下表“原版行号”指该提交，用 `git show c2120cb:backend/scripts/esdf_cpp/voxel_points_to_esdf.cpp` 可复核。
- MrHash：`/root/autodl-tmp/mrhash` 的 `23c98bb09eaf1fe06f54153b046b506303ce599d`，本轮只读其源码/配置。
- Voxblox：`/root/autodl-tmp/envs/distance/ws/src/voxblox` 的 `c8066b04075d2fee509de295346b1c0b788c4f38`。
- 当前历史样本：Job `job_1792219486_ec99dd`，run `20261017_144929_768cd948`；原生 PLY 9,617,925 点。本轮只在16个分散偏移各读32条记录，共512条/12,288字节，不做全文件扫描或转换。512条均RGBA=(255,0,0,0)，weight 1..255，sdf约 -0.399777..+0.400000 m；坐标与0.05 m整数格点偏差至多0.000153格，符合float32舍入。此为有界抽样，不是全量验收。历史manifest没有producer二进制SHA，不能仅用颜色证明历史运行的精确二进制版本。

原转换器只使用Voxblox的Layer/EsdfMap容器及序列化，虽然include了esdf_integrator.h，却没有调用EsdfIntegrator；不能直接把官方ESDF算法的性质归给它。

**更正一：** 没有 `+0.5` 不是 MrHash 漏写体素中心的证据。`voxel_hash_utils.cuh:66–71` 的正变换为 `p=i*h`，`:143–150` 的逆变换按最近整数中心取整；`voxel_data_structures.cu:1309–1318` 在同一采样位置计算sdf；`streamer.cpp:123–152` 导出同一位置。finest格点代表原生中心/采样点，原点就是一个中心。Voxblox `core/common.h::getCenterPointFromGridIndex` 和 `core/block.h:83–92` 才使用 `(i+0.5)*h`。两种网格约定均可成立；错误是未经插值把在一种采样点的数值当作另一种中心的数值。

**更正二：** 当前INS配置并非已证明混合层。`rosbag_runner.py:101` 强制projective_sdf=True；当前run_config的 `mesh.sdf_var_threshold=0`。`voxel_data_structures.cpp:119–125,146–152` 只有threshold>0才调用checkVarSDF/reallocBlocks，初始allocBlock默认resolution=0（`.cuh:246`）。因此固定源码的当前运行路径保持finest层，h=本Job配置的0.05 m；抽样与此一致。混合层是其他启用threshold的配置兼容问题，不再当作当前任务无条件阻断。

## 已证明的问题、触发条件与修复状态

| 项目 / 位置 | 触发与具体影响 | 分类及处理 |
|---|---|---|
| 原版:103–120盲读24字节结构 | ASCII/字段变序/截断/NaN会被误解；NaN weight甚至通过 `<2` 过滤 | **已证明的输入校验错误**。共享`voxel_input.h`严格校验格式/字段/个数、有限数及weight；完整驱动检查截断/尾随数据与零有效样本，失败退出2 |
| 原版:126–133直接按坐标定位后覆盖 | 如h=0.1，同一行的x=0和0.05落同一目标体素；顺序决定最后sdf。h=0.05同层唯一点未必触发重复 | **条件性确定错误**。新驱动对目标索引去重，重复即拒绝，不擅自加权平均/取最小/取绝对值 |
| MrHash整数中心 → Voxblox中心 | h相同时，p=i*h被放进索引i，但该目标中心是(i+.5)h；投影sdf属于原采样点，不属于新中心 | **双方坐标契约差异；不是原导出中心错误**。拒绝非Voxblox中心直接导入；未平移原数据。点到cell近似可以成为显式方案，但须规定误差/碰撞规则；本轮不默许这个近似，也不宣称MrHash中心错误 |
| 原版:132、165–167 | 全部投影sdf直接成为固定种子；斜射平面上投影距离与法向欧氏距离不同。所有观测点还被固定，不能被波前纠正 | **不满足通用ESDF定义，算法设计仍阻断**。只保留未验收诊断分支，不把这个拷贝当作TSDF→ESDF实现 |
| 原版:193–213首次入队即processed | seed A=(0,0,0), d=0先发现C=(1,1,1)，给sqrt(3)；B=(1,1,0),d=.2随后可给C=1.2，却被跳过（单位h=1） | **已证明的最短路错误**。改成best距离松弛，出队时才finalize，过期队列项跳过；Python图参考回归通过，完整C++转换器尚未执行 |
| 原版:195的26邻域路径长度 | 位移(2,1,0)的无障碍路径1+sqrt(2)不等于sqrt(5) | **原算法度量定义问题**。队列修复只修图最短路，绝不将其称为精确欧氏距离；是否采用Voxblox quasi/full Euclidean模式需要显式定义 |
| 原版:200–209未知邻居被allocated/observed=true并赋正距离 | 负seed旁缺席体素也变正；窄带外/被清理/从未有效观测的区域被标为有效正距离 | **已证明的行为；如何扩张尚缺政策依据**。生产禁止；保留显式`--legacy-diagnostic`以供复现，不默认把未知当空闲。没有用填零/abs/改符号“修复”未知区 |
| 原版:325预览坐标用grid origin | ESDF值属于Voxblox中心，预览整体偏半格，相对同层原生查询不一致 | **已证明的输出坐标错误**。改用getCenterPointFromGridIndex，并输出float足够精度；这是修正Voxblox预览语义，不是移动MrHash输入 |
| 原版:231忽略saveToFile返回值 | 磁盘/路径错误仍打印成功 | **已证明的错误处理缺失**。检查bool及PLY写入状态；目录创建失败抛错 |
| 非当前配置threshold>0 / source_h!=target_h | 可能降层、混合尺度；原生PLY没有level/extent字段，颜色仅部分层定义可靠 | **兼容问题**。新输入测试明确拒绝粗层/不同分辨率；当前threshold=0不要求虚构混合层元数据 |

新C++只开放两种互斥显式模式：`--validate-only`（只检查输入，不生成map）及`--legacy-diagnostic`（旧算法诊断）。无正式生产转换入口；诊断输出只能叫 `diagnostic-unaccepted.esdf`、`preview/diagnostic-unaccepted.ply`，不能伪装成平台的map.esdf/result_manifest成功。`run_esdf.sh`生产gate仍保持。未来真实算法实现必须一起更新其CLI/平台契约，不能只删除gate字符串。

## 当前输入的准确语义与映射

1. PLY是同Job Surface manifest中的原生`voxel_points`，world、meter、binary_little_endian；float32 x/y/z/sdf/weight，uint8 RGBA，共24字节。不是mesh或GLB。Mesh阈值与体素导出/转换器权重阈值不能混用。
2. LiDAR固定reader使用projective_sdf=True；`.cu:1318`为`range-voxel_range`，米制未归一化，传感器侧正。截断函数 `voxel_hash_utils.cuh:185–187` 是tau0+range*tau_scale；INS为0.40+range*0，不是所有任务常量。斜射、融合后sdf不能直接等同于欧氏距离。
3. `combineVoxel`在`.cuh:166–180`按积分权重融合sdf、权重饱和；导出`streamer.cpp:132`仅weight>0。转换器原有weight>=2过滤保持，没有改为1或Mesh用的10。weight=1是原生有效低置信样本，按现转换器策略过滤后在目标中保持未知，不能说它是输入坏值；weight<=0/NaN/Inf才拒绝。
4. 缺席代表“导出时没有保留下来的有效sdf样本”：可能窄带外、从未有效观测，或`.cpp:167起 garbageCollect`清理过。既不证明空闲，也不证明占据；不能由这个PLY恢复完整射线可见性。
5. 当前h=0.05来自本Job run_config；native中心在i*h。原版目标索引近似floor(p/target_h)，目标中心是(index+.5)*target_h。新规范输入核心只接受**已经有依据地准备好的**同分辨率Voxblox中心样本：`floor(p/h)`，中心一致性容差1e-3格（float32表示校验），保留原世界坐标和带符号sdf；粗层、重复索引与非中心输入明确拒绝，不做隐含聚合。
6. `distance_input.py`只读头时现报告`source_uniform_finest`、证据和原生采样约定；threshold<=0且extents=1可证明当前固定源码路径不降层。即使手工填入uniform JSON元数据，也不自动令`grid_ready=True`；原始artifact的中心和值并没有因此改变。当前真正待解决的是重采样和ESDF定义，不是缺一个声明字段。

## 仍缺的算法依据与可选方案（不擅自选）

- **世界坐标不变的重采样/聚合**：明确如何由原生整数采样在Voxblox中心插值、如何要求邻域已知、如何传递有效权重，重复/缺邻域如何处理。候选包括仅在必要邻居均有效时作三线性插值、明确误差界和碰撞聚合的point-to-cell近似，或从已知TSDF零交叉重建表面再在声明的支持域计算距离。这些方案有不同支持域、误差及权重含义，双方源码没有规定选哪种。本轮一律拒绝未定义情况，未作固定平移。
- **TSDF→ESDF**：固定Voxblox `test/tsdf_to_esdf.cc` 已示范TsdfVoxel layer→EsdfIntegrator；`esdf_integrator.cc:153–190`区分低权重、fixed band及带符号初始化，`.cc:333–335,408–410`避免直接更新未观测邻居。但fixed band、full/quasi Euclidean模式、最大/默认距离、add_occupied_crust及小误差目标应明确配置并测试，不能随意拿默认值替代平台距离场定义。
- **未知区政策**：候选A仅在可信观测支持域计算/查询，未观测仍invalid；候选B允许有界推断，但需独立标记inferred/hallucinated和查询安全规则，不能沿用observed代表真实观测。原转换器只给最终distance/observed，原PLY又没有射线信息，无法推导出一个已被产品契约接受的扩张政策。
- **其他自适应配置**：若未来threshold>0，需要level/extent可靠导出及统一采样规则。不得从当前全红抽样推断所有配置均为0.05，也不得以此阻断当前finest路径。

## 验证层级与实际结果

- Python参考：14项Distance检查通过（7项几何/图参考，7项输入/配置检查）。平面x=1、ray=(.6,.8,0)：投影sdf=1/.6-t，欧氏法向距离=1-.6t，比例0.6，测试t=1.5和2均在0.4 m投影截断范围内，正负方向均覆盖；参考测试不是Voxblox执行。
- C++共享输入核心：只编译`input_core_test.cpp`及生产驱动共用`voxel_input.h`，没有Voxblox链接/Protobuf/传播/序列化。g++ -O0 -Wall -Wextra -Werror通过，最终2.180秒、峰值121,692 KiB；程序明确输出CPP_INPUT_CORE_ONLY PASS。覆盖字段/空头、正负sdf保留、负索引中心、重复集合检测、错位拒绝、非法/低权重、NaN/Inf。它不证明完整转换器通过。
- 后端回归195项通过，18.794秒，包括既有Pose→Surface、队列、取消、设备与上传。没有本轮新增测试替身冒充真实ESDF。
- `distance_native_checks.py`是**以后**调用实际ELF二进制的驱动，无二进制直接失败，不使用Mock；当前未执行native cases。可测试真实驱动的截断/尾随、空输入、平面输入接受、重复、不同层/尺度、非法数值、错位拒绝。即使将来这些输入测试都通过，仍不代表算法输出平面距离正确。
- 新增`verify_esdf_layer.cpp`供未来同版本真实Protobuf读回，检查几何/非空/有限值、统计observed/negative；未编译运行，且结构读回不替代符号、距离精度、未知mask样本测试。
- 原平台进程全程保留，**未为加载Distance文案重启**：当前页面仍使用上一版本已缓存的未就绪原因；新文案/代码将在计划部署重启后加载。两版都阻止未验收的真实Distance，默认Pose→Surface不变。

机器证据：`/root/autodl-tmp/deployment-preservation/20261020-distance-contract/`。本轮未做大型编译、GPU任务、原生产物处理或完整三阶段验收。恢复步骤/实际命令见`docs/deploy-distance.md`。
