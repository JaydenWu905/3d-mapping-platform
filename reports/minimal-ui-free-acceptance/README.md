# Minimal UI Free 前端改版验收记录

- 本次上传分支：`codex/minimal-ui-free-frontend-only`
- 原本地验收分支：`codex/minimal-ui-free-redesign`
- 模板：Minimal UI Free v3.0.0，commit `69e780a40c455d664b2e13c525faf1d492a072a7`（MIT）
- 依赖：MUI 7.0.1、Emotion 11.14.0、ApexCharts 4.5.0、react-apexcharts 1.7.0、minimal-shared 1.0.7、es-toolkit 1.34.1、react-is 18.3.1（overrides）
- 许可证说明：`frontend/THIRD_PARTY_NOTICES.md`

## 本次前端上传范围（2026-10-18）

- 基于远端 `main` 的 `12663141a9c0457207a38248a6c2245030a4ce33`，提取原本地改版提交 `a4e12211144abce940822c2f5ebb73262bbd41f2` 的前端代码和本目录说明材料。
- 后端整个目录及前端 HTTP 客户端 `frontend/src/api/api.ts` 与上述远端基线完全一致；未修改后端路由、请求/响应契约、调度器或算法适配器。
- 原改版提交包含的演示任务表面输入准备修复未随本次上传发布，仍保存在原本地分支。
- 下方浏览器验收、截图和 JSON 是原本地验收环境的历史记录；该环境包含上述后端演示修复，因此这些记录不能作为本次纯前端版本的三阶段端到端通过证明。

## 本次纯前端发布验证

以下检查于 2026-10-18 在基于远端主分支的独立工作目录重新执行：

| 检查 | 结果 |
| --- | --- |
| `npm.cmd ci --no-audit --no-fund` | 通过 |
| `npm.cmd run typecheck` | 通过 |
| `npm.cmd run build` | 通过；保留已知的 chunk 大小提示 |
| `node tests/poseProgress.test.cjs` | 通过 |
| `node tests/jobDisplay.test.cjs` | 通过 |
| `node tests/progressHistory.test.cjs` | 通过 |
| 后端目录与远端主分支基线逐文件比较 | 无差异 |
| 前端 HTTP 客户端与远端主分支基线比较 | 无差异 |
| 前端代码与原本地改版提交比较 | 无差异 |

## 原本地验收结果

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 依赖安装 | `npm.cmd ci` | 通过（lockfile 已更新并提交） |
| 类型检查 | `npm.cmd run typecheck` | 通过，无输出错误 |
| 生产构建 | `npm.cmd run build` | 通过（仅 chunk >500 kB 提示） |
| 位姿进度语义 | `node tests/poseProgress.test.cjs` | 通过 |
| 任务展示语义 | `node tests/jobDisplay.test.cjs` | 通过 |
| 观测进度采样 | `node tests/progressHistory.test.cjs` | 通过 |
| 浏览器功能验收 | CDP 脚本 `functional.cjs` | 16/16 通过 |
| SSE 断线/重连 | CDP 脚本 `sse-phase.cjs` | before/during/after 三阶段全部通过 |
| 布局审计 | CDP 脚本 `audit-layout.cjs` | 1920×1080、1366×768 均无横向溢出，无按钮裁切 |

### 功能验收覆盖

上传前 bag 大小校验、默认合成演示数据、演示失败阶段选择、创建任务、运行前“暂无数据”、位姿运行曲线、运行中切换阶段、按阶段模拟失败、失败前观测样本、重跑重置历史、取消阶段、中文删除确认、取消删除、确认删除后 404。

### 布局指标（final）

| 页面 | 1920×1080 | 1366×768 |
| --- | --- | --- |
| 任务总览 | 无溢出；2 张图；侧栏 200 / 顶栏 56 | 无溢出；2 张图 |
| 新建任务 | 无溢出；无横向滚动 | 无溢出；无横向滚动 |
| 任务详情 | 无溢出；3D 视口 1126×758 | 无溢出；3D 视口 738×456 |
| 展示模式 | 侧栏隐藏；视口 1280×828；Esc 恢复；canvas 节点复用 | — |

圆角控件统计：`0`（按钮、输入、卡片、对话框均 0px）。正文 18px、按钮 24px、页面标题 32px（详情 30px）、图表坐标轴 16px。

### SSE 断线证据

- `sse-before.json`：`实时连接已建立`，2 张图，观测 7 点，耗时 18 点。
- `sse-during.json`：后端停止后显示 `连接中断，正在重连`，图表保留 7/18 点。
- `sse-after.json`：后端恢复后自动回到 `实时连接已建立`，图表与 canvas 实例均保留。

Vite dev proxy 在 headers 已发送后不会主动关闭 SSE 响应，导致浏览器收不到 `onerror`。已在 `vite.config.ts` 的 proxy `error` 事件中补 `res.end()`；同时 `useJob.ts` 接管重连循环（2s 起指数退避，上限 10s），因为后端不可用时 EventSource 收到 5xx 会永久停止重试。

## 截图索引

- `overview-1920.png` / `overview-1920-full.png`
- `new-job-1920.png` / `new-job-1920-full.png`
- `job-detail-1920.png` / `job-detail-1920-full.png`
- `job-detail-display-1920.png` / `job-detail-display-1920-full.png`
- `overview-1366.png` / `overview-1366-full.png`
- `new-job-1366.png` / `new-job-1366-full.png`
- `job-detail-1366.png` / `job-detail-1366-full.png`
- `acceptance.json`：字体、圆角、图表、视口、展示模式复用的自动审计结果
- `functional.json`：16 项功能验收明细

## 启动方式

```powershell
# 后端
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

访问 `http://127.0.0.1:5173/`。开发服务器把 `/api` 代理到 `127.0.0.1:8000`。

## 已知限制

- 本次验收环境无真实 `ins_longcorridor01` / `oxford_mrhash_lidar` 数据，真实算法链路未在本机执行；演示任务使用 mock 产物。
- 真实两阶段任务的“本任务未请求距离场”由 `frontend/tests/jobDisplay.test.cjs` 覆盖；后端规则要求演示任务必须请求三阶段，浏览器里无法创建真实两阶段任务。
- 17 GB 原始 bag 未实际上传，仅验证了上传前的字节数校验与错误提示。
- Windows 验收环境为后端临时提供了 `fcntl` shim（位于系统临时目录，未进入仓库）；Linux 部署不需要。
- 原本地验收曾使用 `runner_service._needs_surface_input_prep` 跳过演示任务的真实表面输入契约检查；本次纯前端上传不包含该后端修复。远端原有调度逻辑保持不变，新建演示任务在进入表面重建阶段时仍可能受既有输入契约检查阻断，需在独立后端修复中处理。
- 构建存在单个 chunk >500 kB 的 Vite 提示，主要来自 Three.js / ApexCharts，未做进一步拆包。
