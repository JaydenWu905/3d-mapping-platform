const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const SRC = path.join(__dirname, '../src');

/**
 * 现有测试用 transpileModule 直接执行单个纯函数模块。
 * 等待状态模块有两个相对导入，这里加一个最小加载器，保持同样的直接求值方式。
 */
const moduleCache = new Map();

function resolveTs(fromFile, specifier) {
  const base = path.resolve(path.dirname(fromFile), specifier);
  const candidates = [base, `${base}.ts`, path.join(base, 'index.ts')];
  const found = candidates.find(
    (candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile(),
  );
  if (!found) throw new Error(`Cannot resolve ${specifier} from ${fromFile}`);
  return found;
}

function loadTs(file) {
  const absolute = path.resolve(file);
  if (moduleCache.has(absolute)) return moduleCache.get(absolute).exports;

  const source = fs.readFileSync(absolute, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  moduleCache.set(absolute, module);
  const localRequire = (specifier) => {
    if (!specifier.startsWith('.')) {
      throw new Error(`Unexpected external import: ${specifier}`);
    }
    return loadTs(resolveTs(absolute, specifier));
  };
  new Function('exports', 'require', 'module', compiled)(
    module.exports,
    localRequire,
    module,
  );
  return module.exports;
}

const { deriveWaitingPreviewState } = loadTs(
  path.join(SRC, 'components/waitingPreview/state.ts'),
);
const { hasUsablePreview } = loadTs(
  path.join(SRC, 'components/waitingPreview/artifacts.ts'),
);
const {
  buildScannerMap,
  revealedCellCount,
  routeAt,
  sceneArea,
} = loadTs(path.join(SRC, 'components/waitingPreview/route.ts'));

function makeStage(overrides = {}) {
  return {
    stage: 'pose',
    backend: 'glim',
    backend_display: 'GLIM',
    backend_status: 'ready',
    status: 'running',
    phase: null,
    progress: 0,
    current: 0,
    total: 0,
    unit: '',
    message: '',
    elapsed_sec: 0,
    started_at: '2026-10-17T10:00:00Z',
    finished_at: null,
    manifest: null,
    ...overrides,
  };
}

function artifactStage(stageKey, artifactIds, overrides = {}) {
  return makeStage({
    stage: stageKey,
    status: 'completed',
    progress: 100,
    manifest: {
      job_id: 'job-1',
      stage: stageKey,
      backend: 'demo',
      created_at: '2026-10-17T10:00:00Z',
      metrics: {},
      artifacts: artifactIds.map((artifactId) => ({
        artifact_id: artifactId,
        role: 'preview',
        path: `${artifactId}.bin`,
        content_type: 'application/octet-stream',
        size_bytes: 1,
        download_url: `/x/${artifactId}`,
      })),
      errors: [],
      warnings: [],
    },
    ...overrides,
  });
}

/* ---------- 三个阶段的展开量完全来自有效进度 ---------- */

for (const stageKey of ['surface', 'distance']) {
  for (const percent of [0, 20, 50, 80, 100]) {
    const state = deriveWaitingPreviewState(
      makeStage({ stage: stageKey, status: 'running', progress: percent }),
      true,
    );
    assert.equal(state.mode, 'running', `${stageKey} ${percent}% mode`);
    assert.equal(state.percent, percent, `${stageKey} ${percent}% percent`);
    assert.equal(state.reveal, percent / 100, `${stageKey} ${percent}% reveal`);
    assert.equal(state.showScene, true);
    assert.equal(state.animate, true);
  }
}

// 同一位姿阶段走 GLIM 输入发布进度：20% / 50% / 80%。
for (const published of [0, 20, 50, 80]) {
  const state = deriveWaitingPreviewState(
    makeStage({
      stage: 'pose',
      phase: 'input_publishing',
      lidar_total: 100,
      lidar_published: published,
    }),
    true,
  );
  assert.equal(state.percent, published);
  assert.equal(state.reveal, published / 100);
  assert.equal(state.kind, 'input');
}

// 固定快照重复推导结果相同，不包含时间或扫描圈数。
const fixed = makeStage({ stage: 'surface', progress: 40 });
const first = deriveWaitingPreviewState(fixed, true);
const second = deriveWaitingPreviewState(fixed, true);
assert.deepEqual(first, second);

// 进度回退时展开量跟着回退，不锁定历史最大值。
const high = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', progress: 80 }),
  true,
);
const low = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', progress: 20 }),
  true,
);
assert.equal(high.reveal, 0.8);
assert.equal(low.reveal, 0.2);

// 越界/非有限进度按现有语义收敛，不产生虚假展开。
assert.equal(
  deriveWaitingPreviewState(
    makeStage({ stage: 'surface', progress: 140 }),
    true,
  ).reveal,
  1,
);
assert.equal(
  deriveWaitingPreviewState(
    makeStage({ stage: 'surface', progress: Number.NaN }),
    true,
  ).reveal,
  0,
);

/* ---------- GLIM 输入发布完毕后仍在等待导出/关联 ---------- */

for (const phase of ['waiting_glim_export', 'associating']) {
  const state = deriveWaitingPreviewState(
    makeStage({
      stage: 'pose',
      status: 'running',
      phase,
      lidar_total: 10,
      lidar_published: 10,
    }),
    true,
  );
  assert.equal(state.mode, 'running');
  assert.equal(state.standby, true, `${phase} standby`);
  assert.equal(state.reveal, 1);
  assert.equal(state.percentText, '输入发布 100%');
  assert.match(state.title, /等待轨迹导出/);
  assert.doesNotMatch(state.title, /完成/);
  assert.equal(state.animate, true);
}

// 输入发布到 100% 但阶段本身尚未结束时，也只待命，不当作完成。
const inputDone = deriveWaitingPreviewState(
  makeStage({
    stage: 'pose',
    phase: 'input_publishing',
    lidar_total: 8,
    lidar_published: 8,
  }),
  true,
);
assert.equal(inputDone.standby, true);
assert.equal(inputDone.mode, 'running');

// 阶段进度 100% 但状态仍为 running：继续等待，不显示完成。
for (const stageKey of ['surface', 'distance']) {
  const state = deriveWaitingPreviewState(
    makeStage({ stage: stageKey, status: 'running', progress: 100 }),
    true,
  );
  assert.equal(state.mode, 'running');
  assert.equal(state.reveal, 1);
  assert.doesNotMatch(state.title, /已完成/);
}

/* ---------- 未知、排队、未开始 ---------- */

const unknown = deriveWaitingPreviewState(
  makeStage({ stage: 'pose', status: 'running', phase: 'tracking' }),
  true,
);
assert.equal(unknown.percent, null);
assert.equal(unknown.reveal, 0);
assert.equal(unknown.percentText, '进度未上报');
assert.match(unknown.title, /正在发布输入|正在等待位姿进度/);
assert.doesNotMatch(unknown.percentText, /%/);

const queued = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', status: 'queued', progress: 0 }),
  true,
);
assert.equal(queued.mode, 'queued');
assert.equal(queued.percent, null);
assert.equal(queued.reveal, 0);
assert.equal(queued.animate, false);
assert.equal(queued.percentText, '排队中');

const waiting = deriveWaitingPreviewState(
  makeStage({ stage: 'distance', status: 'waiting', progress: 0 }),
  true,
);
assert.equal(waiting.mode, 'not-started');
assert.equal(waiting.reveal, 0);
assert.equal(waiting.animate, false);
assert.equal(waiting.percentText, '尚未开始');

const notRequested = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', status: 'not_integrated' }),
  true,
);
assert.equal(notRequested.mode, 'not-requested');
assert.equal(notRequested.showScene, false);
assert.equal(notRequested.reveal, 0);

/* ---------- 失败、取消、取消中、完成但缺产物 ---------- */

const failed = deriveWaitingPreviewState(
  makeStage({ stage: 'pose', status: 'failed', message: 'boom' }),
  true,
);
assert.equal(failed.mode, 'failed');
assert.equal(failed.showScene, false);
assert.equal(failed.animate, false);

const cancelled = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', status: 'cancelled', progress: 60 }),
  true,
);
assert.equal(cancelled.mode, 'cancelled');
assert.equal(cancelled.showScene, false);
assert.equal(cancelled.percent, null);

const cancelling = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', status: 'cancelling', progress: 60 }),
  true,
);
assert.equal(cancelling.mode, 'cancelling');
assert.equal(cancelling.showScene, true);
assert.equal(cancelling.animate, false);
assert.equal(cancelling.reveal, 0.6);
assert.equal(cancelling.legend, '已停止 · 等待取消');

const completedMissing = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', status: 'completed', progress: 100 }),
  true,
);
assert.equal(completedMissing.mode, 'completed-missing');
assert.equal(completedMissing.showScene, false);
assert.equal(completedMissing.animate, false);
assert.match(completedMissing.title, /没有可用的预览产物/);

/* ---------- 断线与恢复 ---------- */

const disconnected = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', progress: 40 }),
  false,
  true,
);
assert.equal(disconnected.reveal, 0.4);
assert.equal(disconnected.animate, false);
assert.match(disconnected.title, /连接中断/);

const recovered = deriveWaitingPreviewState(
  makeStage({ stage: 'surface', progress: 40 }),
  true,
  false,
);
assert.equal(recovered.reveal, 0.4);
assert.equal(recovered.animate, true);
assert.doesNotMatch(recovered.title, /连接中断/);

// 已终止状态不再显示“正在重连”。
assert.doesNotMatch(
  deriveWaitingPreviewState(
    makeStage({ stage: 'surface', status: 'failed' }),
    false,
    true,
  ).title,
  /连接中断/,
);

/* ---------- 真实产物接管判据 ---------- */

assert.equal(
  hasUsablePreview(artifactStage('pose', ['trajectory_model'])),
  true,
);
assert.equal(hasUsablePreview(artifactStage('pose', ['trajectory_data'])), false);
assert.equal(
  hasUsablePreview(artifactStage('surface', ['surface_model'])),
  true,
);
assert.equal(
  hasUsablePreview(artifactStage('surface', ['mesh_preview'])),
  false,
);
assert.equal(hasUsablePreview(artifactStage('distance', ['slice_xy'])), true);
assert.equal(hasUsablePreview(artifactStage('distance', ['slice_yz'])), true);
assert.equal(
  hasUsablePreview(artifactStage('distance', ['slice_xy', 'slice_xz'])),
  true,
);
assert.equal(hasUsablePreview(artifactStage('distance', ['esdf'])), false);
assert.equal(hasUsablePreview(makeStage({ manifest: null })), false);

/* ---------- 示意路线只由房间和进度决定 ---------- */

const map = buildScannerMap(0);
assert.equal(map.room, 0);
assert.ok(map.route.length > 10);
assert.ok(map.cells.length > 10);

const routeStart = routeAt(map, 0);
const routeEnd = routeAt(map, 1);
assert.ok(Math.abs(routeStart.x - map.route[0].x) < 1e-9);
assert.ok(Math.abs(routeStart.y - map.route[0].y) < 1e-9);
assert.ok(Math.abs(routeEnd.x - map.route.at(-1).x) < 1e-9);
assert.ok(Math.abs(routeEnd.y - map.route.at(-1).y) < 1e-9);

// 同一进度多次取值一致（不随绘制时间变化）。
assert.deepEqual(routeAt(map, 0.37), routeAt(map, 0.37));

const counts = [0, 0.2, 0.5, 0.8, 1].map((progress) =>
  revealedCellCount(map, progress),
);
assert.equal(counts[0], 0);
assert.ok(counts[1] > 0);
assert.ok(counts[2] > counts[1]);
assert.ok(counts[3] > counts[2]);
assert.equal(counts[4], map.cells.length);

// 三个房间的布局/路线稳定且不同。
const roomMaps = [0, 1, 2, 3].map((room) => buildScannerMap(room));
assert.equal(roomMaps[3].room, 3);
assert.deepEqual(
  roomMaps[3].route.map((cell) => cell.key),
  roomMaps[0].route.map((cell) => cell.key),
);
assert.notDeepEqual(
  roomMaps[0].route.map((cell) => cell.key),
  roomMaps[1].route.map((cell) => cell.key),
);

// 紧凑高度仍为底部说明留出区域，避免地图被遮住。
const compact = sceneArea(390, 360);
assert.ok(compact.w > 100 && compact.h > 60);
assert.ok(compact.y + compact.h <= 360 - 164 + 1);
const tall = sceneArea(1280, 760);
assert.ok(tall.w > compact.w && tall.h > compact.h);

/* ---------- 生命周期与进度来源的源码约束 ---------- */

const componentSource = fs.readFileSync(
  path.join(SRC, 'components/WaitingPreview.tsx'),
  'utf8',
);
assert.match(componentSource, /FRAME_INTERVAL_MS = 1000 \/ 30/);
assert.match(componentSource, /DPR_CAP = 2/);
assert.equal((componentSource.match(/requestAnimationFrame\(/g) ?? []).length, 2);
assert.match(componentSource, /cancelAnimationFrame\(/);
assert.match(componentSource, /new ResizeObserver/);
assert.match(componentSource, /observer\.disconnect\(\)/);
assert.match(componentSource, /document\.addEventListener\('visibilitychange'/);
assert.match(
  componentSource,
  /document\.removeEventListener\('visibilitychange'/,
);
assert.doesNotMatch(componentSource, /setInterval|setTimeout/);
assert.doesNotMatch(componentSource, /EventSource|fetch\(|api\./);
assert.match(componentSource, /progress: snapshot\.state\.reveal/);
assert.doesNotMatch(componentSource, /progress:\s*time/);
assert.match(componentSource, /useReducedMotion\(\)/);
assert.match(componentSource, /data-waiting-reveal/);
assert.match(componentSource, /展开量跟随进度；图形为示意，不是真实地图。/);
assert.match(componentSource, /等待互动 · 非实时地图/);

const pageSource = fs.readFileSync(
  path.join(SRC, 'pages/JobDetailPage.tsx'),
  'utf8',
);
assert.match(pageSource, /hasUsablePreview\(stage\)/);
assert.match(pageSource, /function previewHint\(stage: StageDetail\): string/);
assert.match(pageSource, /未请求该阶段/);
assert.match(pageSource, /无可用预览产物/);
assert.match(pageSource, /<WaitingPreview stage=\{stage\} connected=\{connected\} \/>/);
assert.match(pageSource, /key=\{`\$\{job\.job_id\}:\$\{stage\.stage\}`\}/);
assert.doesNotMatch(pageSource, /progress\s*[<>=].*WaitingPreview/);

console.log('Waiting preview states and lifecycle: passed');
