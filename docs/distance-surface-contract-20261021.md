# 本机真实距离场定义与数值验收（2026-10-21）

本次从 a272d7e 接续；旧诊断仍明确未验收，没有将其改名发布。新增正式 `--surface-esdf`：**自定义 TSDF 零等值面几何距离算法，使用真实 Voxblox EsdfVoxel 层存储与序列化**。不是声称调用了官方 EsdfIntegrator，也不是把原 Dijkstra 修复误称为精确欧氏算法。

## 已实施的定义

- 输入限定当前 INS finest 路径：本 Job run_config 中 sdf_var_threshold<=0、voxel_extents_scale=1；source_h=target_h。C++ 对每条记录检查严格 PLY 格式、有限值、正权重、i*h 整数采样及重复索引。坐标只做 float32 格点容差内的整数索引恢复（1e-3 格），**不平移输入世界坐标**。粗层、异分辨率及重复拒绝，不平均覆盖。weight=1 是低置信观测，保留输入记录但不参与支持域。
- 原生源点是 i*h。目标索引 i 的中心是 (i+.5)*h；仅当该源 cell 八角点均存在且 weight>=2 时支持此中心。不是将任一个角点值直接复制到目标中心。
- 每 cell 使用固定 0–7 体对角线的六个四面体；邻 cell 的公共面划分一致。四面体内 TSDF 作线性插值，在异号边上线性求根，构造零面三角形。按同一线性场确定符号；中心在体对角线上，其 TSDF=(d000+d111)/2。**投影 TSDF 只用于零面和符号，不作为欧氏距离的幅值。** 这与在 Voxblox 中直接固定一个较宽投影 TSDF band 不同。
- BVH 仅加速精确 point-to-triangle 最近距离；查询结果是到重建零面（全部三角形并集）的欧氏距离，保留插值场符号。没有对最终距离取绝对值来掩盖符号。正侧继承 MrHash 的传感器侧正约定；融合/噪声造成的零面误差仍存在，不能推导完整实体内部语义。
- 计算半径 2.5 m；无近于此半径的零面或缺任一有效角点，目标保持 unknown。无自由空间推断、无外推、无占据 crust、无未知区填零。observed 在此表示“有效 TSDF 观测角点支持下的计算值”，不表示该中心曾被传感器直接观测。未分配块与分配块中 observed=false 都是未知。传播是全三角形几何最近距离查询，不把传播域另标为观测域。
- 输出 h、16 voxels/side 的真实 Voxblox EsdfVoxel protobuf map.esdf；同版本真实读取器重载验证，失败阻止成功 manifest。计算域仅为上述有限支持域，不是全空间碰撞地图。
- 预览仅 |d|<=1.5 m；固定红−1.5/紫0/蓝+1.5 m 图例，白色表示该像素没有有效预览采样（包含未知及裁剪/投影空缺，不能当作自由空间）。三张切片使用各法向坐标中位数 ±0.1 m，具体中心、范围和数量在 slices_meta.json。相同像素优先取更接近切片中心的样本；原生产物没有该可视化裁剪。

## 为什么采用零面几何距离

固定 Voxblox 官方示例 `voxblox/test/tsdf_to_esdf.cc` 和 `EsdfIntegrator` 实现对 fixed band 直接保留 TSDF 数值。官方文档说明 full/quasi 模式和 fixed band 参数，但不会把任意投影 TSDF 自动校正为精确法向距离。当前没有原始射线可见性，所以不凭空扩张已知空间。选择零等值面和有限支持域，可给出可复现、可数值验证的几何定义，并保留未知语义。

参考：[官方 EsdfIntegrator API](https://voxblox.readthedocs.io/en/latest/api/classvoxblox_1_1EsdfIntegrator.html)、[ESDF 生成说明](https://voxblox.readthedocs.io/en/latest/pages/How-Does-ESDF-Generation-Work.html)。依赖实现仍固定 c8066b04075d2fee509de295346b1c0b788c4f38。

## 实际 ELF 数值检查

运行 `bash ops/continue-gpu.sh native-surface-tests NEW_REPORT_DIR`。脚本调用实际编译转换器，并由真实 Voxblox reader 导出原生层逐体素值，**不拿预览 PLY 代替原生距离读回**。

证据目录 `/root/autodl-tmp/deployment-preservation/20261021-gpu-distance/surface-native-03`，h=.1 m：

| 输入/检查 | 预期与实际 |
|---|---|
| x=.05 平面 | 预期 .05−x，涵盖正负与中心零交叉；最大误差 7.20e−8 m |
| 法向(.6,.8,0)斜平面 | 源投影值=(.03−n·p)/.6；预期欧氏值 .03−n·p；最大误差 7.92e−8 m |
| 三轴等斜平面 | 源投影值=2(.05−n·p)；最大误差 1.124e−7 m |
| 上三项容限 | 固定 2e−6 m，覆盖 float32 坐标/序列化舍入；不是根据实测放宽 |
| R=.35 m 球 | 预期 R−norm(p)；最大误差 .009556 m；预先使用线性插值曲率界 3h²/[8(R−sqrt(3)h)]=.021211 m（零面邻域最小半径 R−sqrt(3)h，插值误差界），不是平面容限放宽 |
| 中心坐标 | 原生读回每个坐标满足 (i+.5)h |
| 缺失角点、weight=1角点 | 精确核对支持体素集合，均恰好使相邻8个cell未知；没有正值传播填充 |
| 重复、空、NaN、weight=0、全低权重、无零交叉 | 均非零退出，无成功输出登记 |
| 2.5 m 半径 | 支持域中超过半径的样本仍未知；解析预期50个有效中心，原生读回恰为50 |
| 保存失败 | 预建 map.esdf 为目录，真实 SaveLayer 失败；退出2 |

另外原有真实 ELF 输入检查14例通过；旧模式诊断读回通过**只证明诊断可运行**。不把这些输入/结构测试当作上述数值证明。真实 shell/Python 阶段适配器的独立合成 fixture 验证：正常结束状态completed；真实保存失败状态failed、退出1、没有成功manifest。两个 fixture 位于证据目录下 `SYNTHETIC_runner_*`，不是真实 Job。

## 局限

结果精确针对离散重建三角形零面，**不是对真实环境几何的精度保证**；平面以外存在离散化及原 TSDF 融合误差。没有恢复被清理的体素、射线自由空间或未观测障碍。自适应/不同源尺度拒绝。不是官方 Voxblox EsdfIntegrator 的输出。不得作为机械臂规划安全验收。原生层与所有下载、预览均在 Job manifest 中明确区分。
