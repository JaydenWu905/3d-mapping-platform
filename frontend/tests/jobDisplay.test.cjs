const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/utils/jobDisplay.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exportsForTest = {};
Object.assign(exportsForTest, require('./loadSource.cjs')('../src/utils/jobDisplay.ts'));

const {
  STAGE_NAMES,
  countJobStatuses,
  filterJobs,
  isStageRequested,
  jobsLastSevenDays,
  jobDisplayStatus,
  statusDistribution,
  visibleStageKeys,
} = exportsForTest;

assert.deepEqual(STAGE_NAMES, {
  pose: '位姿估计',
  surface: '表面重建',
  distance: '距离场',
});

const jobs = [
  { job_id: 'job-run', created_at: '2026-10-17T09:00:00', status: 'running', dataset: 'ins.bag',
    stages: { pose: 'running', surface: 'waiting', distance: 'not_integrated' } },
  { job_id: 'job-queue', created_at: '2026-10-17T08:30:00', status: 'queued', dataset: 'lidar.bag',
    stages: { pose: 'queued', surface: 'waiting', distance: 'not_integrated' } },
  { job_id: 'job-cancel', created_at: '2026-10-16T12:00:00', status: 'cancelling', dataset: 'cam.bag',
    stages: { pose: 'cancelling', surface: 'waiting', distance: 'not_integrated' } },
  { job_id: 'job-done', created_at: '2026-10-16T10:00:00', status: 'completed', dataset: 'ins-2.bag',
    stages: { pose: 'completed', surface: 'completed', distance: 'not_integrated' } },
  { job_id: 'job-fail', created_at: '2026-10-15T10:00:00', status: 'failed', dataset: 'ins-3.bag',
    stages: { pose: 'failed', surface: 'waiting', distance: 'not_integrated' } },
  { job_id: 'job-stop', created_at: '2026-10-14T10:00:00', status: 'cancelled', dataset: 'ins-4.bag',
    stages: { pose: 'cancelled', surface: 'waiting', distance: 'not_integrated' } },
  { job_id: 'job-new', created_at: '2026-10-14T09:00:00', status: 'created', dataset: 'ins-5.bag',
    stages: { pose: 'waiting', surface: 'waiting', distance: 'not_integrated' } },
];

const counts = countJobStatuses(jobs);
assert.equal(counts.total, 7);
assert.equal(counts.running, 3); // running + queued + cancelling
assert.equal(counts.completed, 1);
assert.equal(counts.failed, 1);
assert.equal(counts.cancelled, 1);
assert.equal(counts.created, 1);
assert.equal(jobDisplayStatus('queued'), 'running');
assert.equal(jobDisplayStatus('cancelling'), 'running');
assert.equal(jobDisplayStatus('waiting'), 'created');

const distribution = statusDistribution(jobs);
assert.deepEqual(distribution.map((item) => item.value), [3, 1, 1, 1, 1]);
assert.deepEqual(distribution.map((item) => item.color), [
  '#1877F2',
  '#22C55E',
  '#FF5630',
  '#FFAB00',
  '#00B8D9',
]);

assert.deepEqual(
  filterJobs(jobs, 'JOB-', 'all').map((job) => job.job_id),
  jobs.map((job) => job.job_id),
);
assert.deepEqual(
  filterJobs(jobs, 'ins-2', 'completed').map((job) => job.job_id),
  ['job-done'],
);
assert.deepEqual(
  filterJobs(jobs, '', 'running').map((job) => job.job_id),
  ['job-run', 'job-queue', 'job-cancel'],
);
assert.deepEqual(filterJobs(jobs, 'missing', 'all'), []);
assert.deepEqual(
  filterJobs(jobs, '  INS.BAG  ', 'all').map((job) => job.job_id),
  ['job-run'],
);

const daily = jobsLastSevenDays(jobs, new Date(2026, 9, 17, 12, 0, 0));
assert.equal(daily.labels.length, 7);
assert.equal(daily.labels[0], '10-11');
assert.equal(daily.labels[6], '10-17');
assert.deepEqual(daily.values, [0, 0, 0, 2, 1, 2, 2]);
assert.deepEqual(jobsLastSevenDays([], new Date(2026, 9, 17)).values, [0, 0, 0, 0, 0, 0, 0]);
assert.deepEqual(
  jobsLastSevenDays(
    [{ ...jobs[0], created_at: 'not-a-date' }],
    new Date(2026, 9, 17),
  ).values,
  [0, 0, 0, 0, 0, 0, 0],
);

// requested_stages 优先；旧任务按 not_integrated 回退。
const twoStage = {
  requested_stages: ['pose', 'surface'],
  stages: { pose: 'running', surface: 'waiting', distance: 'not_integrated' },
};
assert.deepEqual(visibleStageKeys(twoStage), ['pose', 'surface']);
assert.equal(isStageRequested(twoStage, 'distance'), false);
const detailTwoStage = {
  requested_stages: ['pose', 'surface'],
  stages: {
    pose: { status: 'running' },
    surface: { status: 'waiting' },
    distance: { status: 'not_integrated' },
  },
};
assert.deepEqual(visibleStageKeys(detailTwoStage), ['pose', 'surface']);
const legacy = {
  stages: { pose: 'completed', surface: 'completed', distance: 'not_integrated' },
};
assert.deepEqual(visibleStageKeys(legacy), ['pose', 'surface']);
const legacyAll = {
  stages: { pose: 'completed', surface: 'completed', distance: 'waiting' },
};
assert.deepEqual(visibleStageKeys(legacyAll), ['pose', 'surface', 'distance']);
assert.deepEqual(visibleStageKeys({ requested_stages: [], stages: legacy.stages }), [
  'pose',
  'surface',
]);

console.log('Job display semantics: passed');
