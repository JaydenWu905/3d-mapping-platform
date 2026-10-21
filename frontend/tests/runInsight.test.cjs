const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(file) {
  const out = {};
  new Function('exports', ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/components', file), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText)(out);
  return out;
}
const { measuredProgress, durationRows, inputEta, historicalStageSeconds, stageEta } = load('runInsight.ts');
const pose = { stage:'pose', backend:'glim', status:'running', phase:'input_publishing', lidar_published:50, lidar_total:100, elapsed_sec:60 };
assert.equal(measuredProgress(pose).percent, 50);
assert.match(measuredProgress(pose).label, /输入发布 50%.*仍在运行/);
assert.equal(measuredProgress({...pose, phase:'waiting_glim_export', lidar_published:100}).kind, 'input');
assert.equal(measuredProgress({...pose, phase:'waiting_glim_export', lidar_published:100}).percent, 100);
assert.equal(measuredProgress({...pose, status:'completed'}).label, '阶段已完成');
const surface = { stage:'surface', backend:'mrhash_lidar', status:'running', phase:'mapping', current:400, total:1539, progress:75 };
assert.equal(measuredProgress(surface).percent, null);
assert.match(measuredProgress(surface).label, /融合调用（非已融合帧数）/);
assert.match(measuredProgress({...surface,current:0}).label, /等待首个进度/);
assert.equal(measuredProgress({stage:'distance',status:'running',progress:80}).percent, null);
assert.equal(measuredProgress({stage:'distance',status:'failed',progress:80}).percent, null);

const job = {job_id:'new',dataset:'same',run_mode:'full',run_scope:{pose:'full'},device_config:{sha256:'config'},preview_job:false,
  backends:{pose:'glim',surface:'mrhash_lidar',distance:'voxel_esdf'},stages:{
    pose:{...pose,status:'completed',elapsed_sec:253,manifest:{runtime_sec:248}},
    surface:{...surface,elapsed_sec:36},
    distance:{stage:'distance',status:'waiting',elapsed_sec:0},
  }};
const rows=durationRows(job,['pose','surface','distance'],{surface:42});
assert.deepEqual(rows.map(r=>r.seconds),[253,42,null]);
assert.deepEqual(rows.map(r=>r.status),['completed','running','waiting']);
assert.equal(durationRows({...job,stages:{...job.stages,surface:{...surface,status:'failed',elapsed_sec:37}}},['surface'])[0].seconds,37);
const historic={...job,job_id:'old',stages:{...job.stages,surface:{...surface,status:'completed',elapsed_sec:200}}};
assert.equal(historicalStageSeconds(job,[historic],'surface'),200);
assert.equal(historicalStageSeconds(job,[{...historic,run_mode:'short'}],'surface'),null);
assert.equal(historicalStageSeconds(job,[{...historic,device_config:{sha256:'other'}}],'surface'),null);
assert.match(stageEta(surface,30,200,null),/参考历史运行，约/);
assert.equal(stageEta(surface,170,200,null),'剩余时间暂无法估算');
assert.equal(stageEta(surface,30,null,null),'剩余时间暂无法估算');
assert.equal(stageEta({...surface,status:'queued'},0,200,null),'剩余时间暂无法估算');
const samples=[{at:0,count:0},{at:20000,count:40},{at:40000,count:80}];
assert.equal(inputEta({...pose,lidar_published:80,lidar_total:100},samples),10);
assert.equal(inputEta({...pose,lidar_published:80,lidar_total:100},[{at:0,count:0},{at:1000,count:40},{at:2000,count:80}]),null);
assert.equal(inputEta({...pose,phase:'associating',lidar_published:80,lidar_total:100},samples),null);
assert.match(stageEta(pose,60,250,10),/仅输入发布/);
console.log('Measured progress, durations and guarded ETA: passed');
