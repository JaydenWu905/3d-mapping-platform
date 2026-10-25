const assert=require('node:assert/strict');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const load=require('./loadSource.cjs');
const {measuredProgress}=load('../src/components/runInsight.ts');
const {StageProgressBar}=load('../src/components/StageProgressBar.tsx');
const {stageProgressPatch}=load('../src/components/stageProgressPatch.ts');
const {mergeStageProgress,mergeJobSnapshot}=load('../src/components/progressMerge.ts');
const surface={stage:'surface',backend:'mrhash_lidar',status:'running',phase:'mapping',progress:0,current:3,total:10,progress_run_id:'run-a',progress_started_at:'2026-10-24T00:00:00Z',progress_seq:3,progress_scope:'input',selected_frames:10,visited_frames:4,matched_frames:3,fused_frames:3,skipped_frames:1,elapsed_sec:10};
for(const [fused,expected] of [[0,0],[3,30],[9,90],[10,100]]){
 const s={...surface,fused_frames:fused};assert.equal(measuredProgress(s).percent,expected);
 const text=measuredProgress(s).label;assert(text.includes('已选中')&&text.includes('已关联')&&text.includes('已融合')&&text.includes('已跳过'));
 assert(text.includes('非整个阶段完成'));
 assert(renderToStaticMarkup(React.createElement(StageProgressBar,{stage:s})).includes(`width:${expected}%`));
}
for(const phase of ['exporting_native','exporting_mesh','exporting_voxels','building_preview','finalizing']){
 const s={...surface,phase,fused_frames:10};assert.equal(measuredProgress(s).percent,null);
 const html=renderToStaticMarkup(React.createElement(StageProgressBar,{stage:s}));assert(html.includes('处理中'));assert(!html.includes('aria-valuenow'));
}
assert(measuredProgress({...surface,counter_age_sec:20}).label.includes('暂无新计数'));
const almost={...surface,fused_frames:9999,selected_frames:10000};
assert(measuredProgress(almost).label.includes('99.9%'));
assert(!renderToStaticMarkup(React.createElement(StageProgressBar,{stage:almost})).includes('aria-valuenow="100"'));
const distance={...surface,stage:'distance',backend:'voxel_esdf',progress_scope:'step',phase:'distance_computation',current:4,total:10};
assert.equal(measuredProgress(distance).percent,40);assert.equal(measuredProgress(distance).kind,'step');
assert(measuredProgress(distance).label.includes('仅当前环节'));
assert.equal(measuredProgress({...distance,total:0,progress_scope:'none'}).percent,null);
assert(measuredProgress({...distance,total:0,progress_scope:'none'}).label.includes('已处理 4'));
for(const status of ['failed','cancelled','cancelling'])assert.equal(measuredProgress({...distance,status}).percent,null);
assert.equal(measuredProgress({...distance,status:'completed'}).percent,100);

const old={...surface,progress_seq:2,fused_frames:2,current:2};
assert.equal(mergeStageProgress(surface,old),surface);
assert.equal(mergeStageProgress(surface,{...old,progress_run_id:'old',progress_started_at:'2025-01-01'}),surface);
assert.equal(mergeStageProgress(surface,{phase:'mapping',current:1}),surface);
const stopping={...surface,status:'cancelling'};assert.equal(mergeStageProgress(stopping,{...surface,progress_seq:10}),stopping);
const final={...surface,status:'completed',progress_seq:5};assert.equal(mergeStageProgress(final,{...surface,progress_seq:6}),final);
const newer=mergeStageProgress(final,{...surface,progress_run_id:'run-b',progress_started_at:'2026-10-25T00:00:00Z',progress_seq:0,fused_frames:0});assert.equal(newer.progress_run_id,'run-b');
assert.equal(mergeStageProgress(surface,{...surface,elapsed_sec:2}).elapsed_sec,10);
const job={job_id:'same',name:'任务',status:'running',requested_stages:['surface'],stages:{surface}};
assert.equal(mergeJobSnapshot(job,{...job,stages:{surface:old}}).stages.surface.fused_frames,3);
assert.equal(mergeJobSnapshot({...job,status:'completed',stages:{surface:final}},job).status,'completed');
const patch=stageProgressPatch({...surface,progress_seq:4,fused_frames:5});assert.equal(patch.fused_frames,5);assert.equal(patch.progress_seq,4);
console.log('Structured counts, phase completion, quiet state and stale REST/SSE rejection: passed');
