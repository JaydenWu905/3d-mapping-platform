# 同设备 Livox 新序列上传：CPU 验证与部署记录

分支：`feature/livox-new-sequence-upload`。原发布 tag `ins-two-stage-20261015` 指向 `2445a692f646956c1dc3937096b2c408e4cc239c`，本功能分支从该提交开始。本轮没有运行 GLIM/MrHash，没有用原 bag 的改名、截取或重打包文件冒充新采集序列。

## 结果

- 后端全量 CPU 测试：161 项通过；新增上传/运行范围定向测试：11 项通过。
- bridge Python 的真实合成 ROS1 bag 测试：3 个测试方法通过，覆盖不同大小与消息数的上传注册、缺话题、错误类型、坏文件/坏消息、重复 record/header 时间、帧 ID 不匹配、错误 timebase、坏点/IMU 值、空帧及 IMU 覆盖不足。合成数据只证明代码行为。
- 前端 `NODE_OPTIONS=--max-old-space-size=512 npm run build` 通过。默认 Node 堆的首次构建被 2 GiB 容器限制终止；后续受限堆构建完成。
- 原 INS bag 使用最终预检程序全包流式读取通过：ROS1 bag v2.0；LiDAR 1539 条，IMU 30770 条，检查点 30,756,384；无效点、空帧、点数不一致、范围滤波后空帧均为 0。LiDAR header 范围 `1717493095701965809..1717493249502075434 ns`，IMU header 范围 `1717493095784397125..1717493249634888887 ns`。最大逐点偏移 `101398483 ns`，最大 timebase/header 差 `242 ns`。预检提示 IMU 未覆盖 LiDAR 起始边缘（约 82 ms）；其余结构规则通过。
- 部署后 `ops/platform.sh status` 显示 backend/frontend 运行，后端 `/api/health` 返回 `ok`，`/api/uploads/profiles` 同时列出原固定样本与新同设备 profile。原完整验收 Job 的只读 API 保持可访问。未创建真实新序列 Job。

## 验收边界

服务器发现另一份 M3DGR MID-360 bag，但其话题与此 profile 不同，且没有经核实的同设备安装和标定来源；本轮未使用。新入口的 CPU 通过只代表结构和所选设备配置满足运行前提。真实新采集序列的 Pose→Surface、时间关联、融合计数、几何结果及精度仍待另行验收。交接外参和 IMU 单位仍待来源确认。
