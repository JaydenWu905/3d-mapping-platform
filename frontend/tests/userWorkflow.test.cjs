const assert=require('node:assert/strict');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const load=require('./loadSource.cjs');
const {jobDisplayName,jobNameError,normalizedJobName}=load('../src/utils/jobName.ts');
const {filterJobs}=load('../src/utils/jobDisplay.ts');
assert.equal(normalizedJobName('  走廊  扫描 A-1  '),'走廊 扫描 A-1');
for(const v of ['', ' ', '中'.repeat(81),'a\nb','a\u202eb','<script>','a\\b'])assert(jobNameError(v),v);
for(const v of ['走廊扫描测试', 'Area A/2（东侧）— #1', '中'.repeat(80)])assert.equal(jobNameError(v),null);
assert.equal(jobDisplayName({created_at:'2026-10-21T08:05:03'}),'建图任务 · 10-21 08:05');
assert.equal(jobDisplayName({name:'走廊扫描测试',job_id:'internal'}),'走廊扫描测试');
assert.equal(jobDisplayName({}),'未命名任务');
const jobs=[{job_id:'a',name:'同名任务',dataset:'d',status:'created',created_at:''},{job_id:'b',name:'同名任务',dataset:'d',status:'created',created_at:''}];
assert.deepEqual(filterJobs(jobs,'同名','all').map(j=>j.job_id),['a','b']);

const {resultMetrics,coordinateRange,artifactLabel}=load('../src/components/resultPresentation.ts');
const manifest={schema_version:'1',stage:'surface',backend:'mrhash_lidar',runtime_sec:29.754,metrics:{vertices:3170730,faces:2387330,preview_faces:499999,preview_simplification_applied:true,preview_bounds:[[-4.025,-13.062100410461426,-1.475],[72.7249984741211,4.1861572265625,5.125]],preview_sha256:'a'.repeat(64),preview_method:'long-method'.repeat(100)},artifacts:[
 {artifact_id:'surface_mesh',role:'data',path:'native/original.ply',content_type:'application/octet-stream',download:true},
 {artifact_id:'surface_model',role:'preview',path:'preview/model.glb',content_type:'model/gltf-binary',download:true},
 {artifact_id:'no_download',role:'preview',path:'preview/only.png',content_type:'image/png'},
 {artifact_id:'extra/data',role:'data',path:'native/record.json',content_type:'application/json',download:true},
]};
const raw=JSON.stringify(manifest),rows=resultMetrics('surface',manifest);
assert.equal(JSON.stringify(manifest),raw);
assert(rows.some(r=>r.label==='原生网格顶点'&&r.value==='3,170,730 个'));
assert(rows.some(r=>r.value==='29.75 秒'));
assert(!JSON.stringify(rows).includes('long-method'));
assert(!JSON.stringify(rows).includes('aaaaaaaa'));
assert.equal(coordinateRange(manifest.metrics.preview_bounds).split('\n').length,3);
assert.match(coordinateRange(manifest.metrics.preview_bounds),/72.72/);
assert.equal(coordinateRange([1,2,3]),null);
assert.equal(resultMetrics('pose',{...manifest,metrics:{matched_ratio:.992203,pose_count:1527}}).find(r=>r.label==='时间关联比例').value,'99.22 %');
assert.equal(resultMetrics('distance',{...manifest,metrics:{resolution_m:.123456}}).find(r=>r.label==='体素分辨率').value,'0.123 m');
assert.equal(artifactLabel(manifest.artifacts[0],manifest),'原生 Mesh（PLY）');
assert.equal(artifactLabel(manifest.artifacts[1],manifest),'简化 GLB 预览');
const {ArtifactsPanel}=load('../src/components/ArtifactsPanel.tsx');
const html=renderToStaticMarkup(React.createElement(ArtifactsPanel,{jobId:'immutable id',stage:'surface',manifest}));
assert.equal((html.match(/href=/g)||[]).length,3);
for(const a of manifest.artifacts.filter(a=>a.download))assert(html.includes(`/api/jobs/immutable%20id/stages/surface/artifacts/${encodeURIComponent(a.artifact_id)}`));
assert(!html.includes('/artifacts/no_download'));
const {RawResultDetails}=load('../src/components/ResultDetails.tsx');
const technical=renderToStaticMarkup(React.createElement(RawResultDetails,{manifest}));
assert(technical.includes('13.062100410461426')&&technical.includes('a'.repeat(64)));
console.log('Task names, legacy fallback, readable values, exact raw values and download links: passed');
