# 运行页面交互与可读性更新 · 2026-10-21

已实现并部署到现有 `http://127.0.0.1:5173`。本次只修改前端和本报告；不修改算法、调度、API/SSE处理、真实进度计算、统计字段或产物。初始分支 `integrate/three-modules-20261020`，HEAD `9a01f52`，工作区干净；已有本地提交全部保留，没有推送或修改远端PR。

证据、截图、构建日志与回滚入口：`/root/autodl-tmp/deployment-preservation/20261021-ui-readability/`。

- 等待小车及地图生成代码已移除。改为紧凑SVG处理示意：位姿扫描连点、表面小体素拼合、距离轮廓线；不读取完成比例、计数或耗时，不模拟当前数据的地图。每18秒最多轮换一次阶段短句；输入、导出、关联、融合、距离计算、整理结果采用不同文案。
- 排队、等待前序、取消、失败停止正常处理动画；失败文案保持直接。减少动态效果偏好下为静态显示；标签页隐藏时停止动效和文案计时，没有自己的高频Canvas/RAF循环。文案轮换不做aria-live播报，避免重复打扰。
- 真实进度独立留在阶段卡片；原 `progressBarState` 计算函数与改动前逐字一致。运行中Surface仍按原始上报值显示“处理计数”，不会把调用计数命名成“已融合”。只有完成结果的 `metrics.fused_frames` 才显示“已融合”；原始单位、tqdm含义和消息移入默认折叠技术详情。
- 正常运行、排队、完成、取消不再显示“当前阶段不可运行”黄色警告。等待前序使用明确依赖关系，不承诺自动开始；只有失败或等待中的真实依赖/配置阻断展示错误/警告。后端“就绪/实验性”能力状态移入技术详情，避免与实际任务状态混淆。
- 主区域提供“处理状态 / 真实结果”切换，已有结果始终有直接入口，不会被示意动画遮住；新增当前阶段“下载原生产物”入口。完成后继续直接展示真实查看器。未知区域、距离单位与必要图例保持可见；较长ESDF算法解释折叠。
- 完整/短段模式及实际帧范围留在主区域；旧任务缺少模式/范围时显示未登记，不推断为完整运行。标定依据保留一句简短提示，完整边界说明放在详情。
- 全局CSS字号变量及MUI主题统一为正文/控件约16px、次要说明14px、阶段标题20px；清理局部小字号覆盖，同步调整行高、按钮高度和工具栏换行。覆盖新建、设备选择、任务详情、列表、阶段卡片、查看器与日志。
- 去掉主区域与右侧对相同计数/进度的重复；页面观测图表、原始字段放进技术详情。详情默认关闭且展开时才挂载图表/日志；没有足够数据时不画空图表。

验证结果：

- `npm --prefix frontend run typecheck` 通过。
- `node --test frontend/tests/*.test.cjs`：5个测试文件通过；保留SSE计数与实际进度条渲染检查，替换旧小车实现约束测试为状态、依赖、失败优先级、真实统计含义及动画独立性测试。
- `npm --prefix frontend run build -- --outDir /root/autodl-tmp/deployment-preservation/20261021-ui-readability/dist-candidate` 通过，包含完整TypeScript构建。仅有既有大bundle提示；没有新增动画依赖。
- Playwright/Chromium：23组隔离浏览器检查，覆盖三个阶段、输入/导出/关联、排队、等待前序、完成、失败、取消及取消中；验证减少动态效果、visibilitychange暂停、18秒文案轮换后API百分比不变，以及处理中查看已有真实结果。
- 1920×1080、1366×768、700×900、390×844检查均无页面横向溢出。新建页另在4个尺寸检查设备下拉框、三阶段选择、短段1–100帧说明；控件字号实测16px。
- 生产5173只读检查现有Job `job_1792547241_905fcb` 的真实Pose/Surface/ESDF预览、下载、日志与技术详情展开；无pageerror、失败接口或写请求。实际浏览器下载原生轨迹，SHA与当前manifest一致；日志实测14px。窄屏展开详情后仍无横向溢出。
- 隔离状态数据只在浏览器中拦截GET及模拟SSE，未创建测试Job；所有非GET请求被测试护栏拒绝，记录的写请求为0。运行中/失败等截图标明 `UI_ONLY_*` 和演示标识，不是实际算法运行。
- 初检时既有Job的Distance为等待，工作期间现有Job状态有更新；本轮没有发起或干预算法、没有回写这些变化。部署前后32个Job元数据文件逐项SHA一致，结果见 `job-preservation.json`。

代表截图（运行状态截图均为隔离UI夹具，真实结果截图来自现有Job）：

| 内容 | 截图 |
|---|---|
| 表面处理中，1366宽 | [处理示意](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/surface-running-mapping-1366.png) |
| 等待位姿完成 | [等待前序](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/waiting-dependency.png) |
| 失败停止动效 | [失败状态](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/distance-failed-conversion_failed-1366.png) |
| 390宽 | [窄屏运行布局](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/responsive-surface-390.png) |
| 新建与设备选择 | [新建任务页](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/new-page-1366.png) |
| 部署后真实模型 | [Surface结果](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/deployed-real-surface.png) |
| 部署后真实距离切片 | [ESDF结果](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/deployed-real-distance.png) |
| 窄屏技术详情与日志 | [展开详情](/root/autodl-tmp/deployment-preservation/20261021-ui-readability/deployed-expanded-details-390.png) |

部署采用“先复制不可变哈希资源，再原子替换index.html”，保留旧哈希资源供已打开页面使用。前端PID15784、后端PID15768均未重启；没有中断任务。访问原地址后按 **Ctrl+Shift+R**（macOS为Cmd+Shift+R）强制刷新。

如仅回滚本次UI，无需重启服务或改动Job；旧资源仍在，恢复入口文件即可：

```bash
cd /root/autodl-tmp/3d-mapping-platform-integrated
python3 - <<'PY'
from pathlib import Path
import os, shutil
backup=Path('/root/autodl-tmp/deployment-preservation/20261021-ui-readability/frontend-index-before.html')
target=Path('frontend/dist/index.html')
temp=target.with_name('index.rollback')
shutil.copy2(backup,temp)
os.replace(temp,target)
PY
```

本次不重新验证建图算法或规划安全，也没有重新运行GLIM/MrHash/Distance。完整证据见 `browser-results.json`、`browser-new-results.json`、`browser-deployed-results.json`、`deployment.json` 与各检查日志。
