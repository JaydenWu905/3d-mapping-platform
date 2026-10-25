const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = {exports:{}}; cache.set(file,module);
  const code = ts.transpileModule(fs.readFileSync(file,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const req = spec => load(path.resolve(path.dirname(file),spec)+'.ts');
  new Function('exports','require','module',code)(module.exports,req,module);
  return module.exports;
}
const {stageNotice,waitingTitle,waitingMessages,dependencyLabel}=load(path.resolve(__dirname,'../src/components/waitingPreview/presentation.ts'));
const {progressLabel,progressBarState,stageMessageLabel}=load(path.resolve(__dirname,'../src/components/progressLabel.ts'));
const stage=(key='pose',status='running',phase='input_publishing')=>({stage:key,status,phase,backend:key==='pose'?'glim':'test',progress:37,current:14,total:100,elapsed_sec:22,can_run:false,run_blocked_reason:'Stage already running',message:''});
for(const key of ['pose','surface','distance']) {
 for(const status of ['running','queued','completed','cancelled','cancelling']) assert.equal(stageNotice(stage(key,status)),null);
 const failed=stage(key,'failed');assert.equal(stageNotice(failed).severity,'error');assert.doesNotMatch(waitingMessages(failed).join(),/拼图|距离尺|马上|预计/);
 const before=stage(key);const frozen=JSON.stringify(before);waitingTitle(before);waitingMessages(before);progressLabel(before);assert.equal(JSON.stringify(before),frozen);
}
const dependency=stage('surface','waiting');dependency.run_blocked_reason='Pose must be completed before running Surface';
assert.equal(dependencyLabel(dependency),'等待位姿估计完成');assert.equal(waitingTitle(dependency),'等待位姿估计完成');assert.equal(stageNotice(dependency),null);
assert.doesNotMatch(waitingMessages(dependency).join(),/自动|马上|分钟/);
assert.match(stageMessageLabel({...stage('distance','failed'),message:'Completed'}),/运行失败/);
assert.match(stageMessageLabel({...stage('surface','failed'),message:'正在融合'}),/运行失败/);
const config=stage('distance','waiting');config.run_blocked_reason='Missing executable';assert.equal(stageNotice(config).severity,'warning');
const input=stage();const exporting={...input,phase:'waiting_glim_export'};const association={...input,phase:'associating'};
assert.notDeepEqual(waitingMessages(input),waitingMessages(exporting));assert.notDeepEqual(waitingMessages(exporting),waitingMessages(association));
const s=stage('surface');s.unit='已完成融合调用 / 全包 LiDAR';s.message='tqdm 计数为已完成融合调用；分母是全包消息数';
assert.equal(progressLabel(s),'处理计数 14 / 100');assert.doesNotMatch(stageMessageLabel(s),/tqdm|融合调用|分母/);
s.status='completed';s.manifest={metrics:{fused_frames:88,selected_frames:100}};assert.equal(progressLabel(s),'已融合 88 帧 · 选中 100 帧');
// Decoration does not depend on changing actual progress, counters or time.
const before=waitingMessages(input);input.progress=91;input.current=99;input.elapsed_sec=900;assert.deepEqual(waitingMessages(input),before);
input.lidar_published=37;input.lidar_total=80;assert.equal(progressBarState(input).percent,46.25);
console.log('stage presentation: lifecycle, dependencies, real counts and progress independence passed');
