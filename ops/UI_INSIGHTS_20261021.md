# 任务详情耗时、进度、ETA 与预览教学（2026-10-21）

## 当前部署

- 分支：`integrate/three-modules-20261020`；本轮只改前端展示与测试。
- 页面：`http://127.0.0.1:5173`，Vite preview 直接读取 `frontend/dist`；后端 `127.0.0.1:8000`。本轮无需重启服务，也没有启动算法或修改 Job 产物。
- 刷新：浏览器 `Ctrl+Shift+R`（macOS `Cmd+Shift+R`）。检查服务：`bash ops/platform.sh status`。
- 证据与截图：`/root/autodl-tmp/deployment-preservation/20261021-ui-insights/`。其中 `UI_ONLY_*` 是浏览器 GET 拦截的隔离状态，绝非服务器 Job；`real-completed-*` 是当前真实已完成 Job `job_1792547241_905fcb` 的只读页面。

## 可信数据的显示规则

右侧“各阶段耗时比较”常显，包含本任务请求的 Pose、Surface、Distance。完成、失败和取消用本 Job `stage.elapsed_sec`，缺失时才用本 Job `manifest.runtime_sec`；运行中用后端实时报的 `elapsed_sec` 并在两次 SSE 之间本地续计。等待显示“尚未开始”，没有把它作为 0 秒纳入最长条。条宽以当前有效耗时最大值归一，行与数值列宽保持固定；无数据给简短提示。

Pose 的唯一运行百分比来自 GLIM bridge 的 `lidar_published/lidar_total`，明确标为**输入发布**。即使输入达到 100%，GLIM 导出和轨迹关联仍按运行中呈现。完成后显示阶段完成。Surface 的 `current/total` 是 MrHash tqdm 的**已完成融合调用/全包 LiDAR 消息**，无法推出已融合帧比例；运行时仅显示调用数，不显示百分比。最终 `manifest.metrics.fused_frames` 才称“已融合”。Distance 适配器的 10/80 是环节事件而非连续工作量，运行时不显示百分比。顶部阶段卡、等待区和右侧摘要共用这些规则；装饰动画完全不参与进度。技术详情中的本页观测图也只取上述可计量值。

预计剩余时间仅在运行时出现，并标明来源。Pose 输入发布需在当前页面观察至少 30 秒、增长至少 20 帧且达到总量 5%，前后半段速率相差不超过 1.5 倍，才按剩余输入量估计**输入发布**时间。刷新页面后重新积累本次速率样本。否则可读取其他已完成 Job，严格匹配相同数据集、运行模式、运行范围、设备配置 SHA 与阶段后端；显示该阶段历史耗时中位数减去本次已运行时间，并标“参考历史运行”。历史参考只在已运行时间低于历史耗时的 80% 时显示，避免倒数到 0 或负数。无匹配、排队、准备期间无可用参考、超出历史范围和不稳定速率均显示“剩余时间暂无法估算”，已运行时间照常更新。没有整体估计百分比。

## 预览教学与字体

等待区保留轻量的阶段示意和“处理示意”标识，新增 10 秒轮换的介绍/操作提示；支持上一条、下一条，悬停/键盘焦点、后台页或减少动态效果时停止自动轮换。Pose、Surface 的操作依据 `OrbitControls`、重置按钮和 Surface 材质选择器；Distance 依据 XY/XZ/YZ 切片按钮、观测掩码及梯度箭头开关。已有前序结果时提供真实结果按钮。结果尚未可用时仅作文字教学，不伪造可点结果。原生产物仍通过登记的下载接口获取。

全站正文与表单主题字号提高到 18px，次要说明 16px，标题 22px 起；按钮、侧栏提示、状态标签、图表标签和预览工具栏一并调整。日志保持紧凑。查看器和窄屏区域保留弹性换行。

## 验证与限制

- `node --test frontend/tests/*.test.cjs`：7 组通过；覆盖耗时状态、可信计数、输入进度 100% 不等于阶段完成、受限 ETA、提示与查看器功能对应等；SSE 更新及刷新由浏览器检查。
- `npm run typecheck`、`npm run build`：通过。Vite 仍提示原有大 bundle（`react-apexcharts` 等）；本轮没有新增依赖。
- Playwright Chromium：1920×1080、1366×768、390×844 下的隔离 Pose/Surface/Distance 运行状态和真实已完成 Job 通过；无横向溢出、页面错误或非 GET 请求。模拟 SSE 将 Pose 输入从 50% 更新至 100% 仍显示运行中；刷新后恢复 REST 读数。真实 Job 的三个预览均加载，Distance 原生 `esdf_map` 下载 117,174,044 字节且 SHA-256 与当前 manifest 一致。新建页表单实测 18px。
- 浏览器隔离状态的历史 ETA 从真实已完成 Job 的只读 API 获取，时间匹配规则见上；这不是新算法任务。真实 Job 的产物时间与 SHA 以当时 API/manifest 为准，不能把旧验收快照当作本轮重新验收。
- 回滚：将证据目录的 `index-before.html` 复制至 `frontend/dist/index.html`；前一版引用的静态资源已保留在 `dist/assets`。不需要重启服务。
