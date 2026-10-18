const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/components/progressLabel.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exportsForTest = {};
new Function('exports', compiled)(exportsForTest);
const {
  progressLabel,
  posePhaseLabel,
  stageProgressText,
  progressBarState,
  unitLabel,
  formatElapsed,
  stagePhaseLabel,
  stageMessageLabel,
  blockedReasonLabel,
} = exportsForTest;
const patchSource = fs.readFileSync(path.join(__dirname, '../src/components/stageProgressPatch.ts'), 'utf8');
const patchCompiled = ts.transpileModule(patchSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const patchExports = {};
new Function('exports', patchCompiled)(patchExports);
const patch = patchExports.stageProgressPatch({ stage: 'pose', phase: 'input_publishing',
  lidar_published: 37, lidar_total: 80, imu_published: 740,
  input_updated_at: '2026-10-17T10:00:00' });
assert.equal(patch.lidar_published, 37);
assert.equal(patch.imu_published, 740);
assert.equal(patch.input_updated_at, '2026-10-17T10:00:00');
assert.equal(patch.progress, undefined);

const stage = { stage: 'pose', backend: 'glim', status: 'running', phase: 'input_publishing',
  progress: 0, lidar_published: 37, lidar_total: 80, imu_published: 740, imu_total: 1600 };
assert.match(progressLabel(stage), /LiDAR 已发布 37\/80/);
assert.match(progressLabel(stage), /输入发布进度 46%/);
assert.match(progressLabel(stage), /IMU 已发布 740\/1600/);
assert.equal(stageProgressText(stage), '输入发布');
assert.doesNotMatch(stageProgressText(stage), /46%|100%/);

stage.lidar_total = 0;
stage.imu_total = 0;
assert.match(progressLabel(stage), /总量未知/);
assert.doesNotMatch(progressLabel(stage), /%/);
stage.phase = 'waiting_glim_export';
assert.equal(posePhaseLabel(stage), '输入发布完成，正在等待 GLIM 导出');
stage.phase = 'associating';
assert.equal(posePhaseLabel(stage), '轨迹关联与产物生成');
stage.status = 'failed';
assert.equal(posePhaseLabel(stage), '位姿估计失败');
stage.status = 'completed';
stage.progress = 100;
assert.equal(stageProgressText(stage), '阶段 100%');

// 展示层中文标签：单位、耗时、环节、消息与不可启动原因。
assert.equal(unitLabel('frame'), '帧');
assert.equal(unitLabel('voxel'), '体素');
assert.equal(unitLabel('秒'), '秒');
assert.equal(formatElapsed(42), '42 秒');
assert.equal(formatElapsed(118), '1 分 58 秒');
assert.equal(formatElapsed(3720), '1 小时 2 分');
assert.equal(formatElapsed(0), '—');
const surfaceStage = {
  stage: 'surface',
  backend: 'mrhash',
  status: 'running',
  phase: 'mapping',
  message: 'Fusing frames 12/40',
  progress: 30,
};
assert.equal(stagePhaseLabel(surfaceStage), '表面融合');
assert.equal(stageMessageLabel(surfaceStage), '正在融合 12 / 40 帧');
assert.equal(stageMessageLabel({ ...surfaceStage, message: 'Completed' }), '已完成');
assert.equal(stageMessageLabel({ ...surfaceStage, message: 'Tracking pose 5/9' }), '位姿跟踪 5 / 9 帧');
assert.equal(blockedReasonLabel("Backend 'x' not in registry"), '所选后端未注册（x）');
assert.equal(
  blockedReasonLabel('Pose must be completed before running Surface'),
  '需先完成位姿估计，才能运行表面重建',
);
assert.equal(blockedReasonLabel('Stage already completed'), '阶段已完成');

// Simulate three SSE count updates and inspect the actual rendered fill width.
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const barSource = fs.readFileSync(path.join(__dirname, '../src/components/StageProgressBar.tsx'), 'utf8');
const barCompiled = ts.transpileModule(barSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const barExports = {};
new Function('require', 'exports', barCompiled)((name) =>
  name === './progressLabel' ? exportsForTest : require(name), barExports);
const { StageProgressBar } = barExports;
for (const [published, expected] of [[10, '10%'], [50, '50%'], [100, '100%']]) {
  const update = patchExports.stageProgressPatch({ stage: 'pose', phase: 'input_publishing',
    lidar_published: published, lidar_total: 100 });
  const liveStage = { stage: 'pose', backend: 'glim', status: 'running', progress: 0, ...update };
  const cardBar = renderToStaticMarkup(React.createElement(StageProgressBar, { stage: liveStage }));
  const detailBar = renderToStaticMarkup(React.createElement(StageProgressBar, { stage: liveStage, large: true }));
  for (const html of [cardBar, detailBar]) {
    assert.match(html, new RegExp(`style="width:${expected}"`));
    assert.match(html, /aria-label="输入发布进度"/);
    assert.doesNotMatch(html, /progress-indeterminate|progress-activity/);
  }
}
const exportStage = { stage: 'pose', backend: 'glim', status: 'running', phase: 'waiting_glim_export',
  progress: 0, lidar_published: 100, lidar_total: 100 };
assert.equal(progressBarState(exportStage).percent, 100);
assert.equal(stageProgressText(exportStage), '输入发布完成，正在等待 GLIM 导出');
const exportBar = renderToStaticMarkup(React.createElement(StageProgressBar, { stage: exportStage }));
assert.match(exportBar, /style="width:100%"/);
assert.match(exportBar, /progress-activity/);
assert.doesNotMatch(stageProgressText(exportStage), /阶段 100%/);
const startBar = renderToStaticMarkup(React.createElement(StageProgressBar, {
  stage: { ...exportStage, phase: 'starting_glim', lidar_published: 0 },
}));
assert.doesNotMatch(startBar, /progress-bg/);
assert.match(startBar, /progress-activity/);
assert.equal(progressBarState({ ...exportStage, phase: 'input_publishing', lidar_total: 0 }).percent, null);
for (const file of ['StageCard.tsx', '../pages/JobDetailPage.tsx']) {
  const source = fs.readFileSync(path.join(__dirname, '../src/components', file), 'utf8');
  assert.match(source, /<StageProgressBar stage=\{/);
}
const css = fs.readFileSync(path.join(__dirname, '../src/styles.css'), 'utf8');
assert.doesNotMatch(css, /progress-indeterminate|progress-sweep/);
console.log('Pose progress labels: passed');
