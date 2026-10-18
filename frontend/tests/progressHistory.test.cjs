const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/utils/progressHistory.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exportsForTest = {};
new Function('exports', compiled)(exportsForTest);

const {
  MAX_PROGRESS_SAMPLES,
  PROGRESS_SAMPLE_INTERVAL_MS,
  appendProgressSample,
} = exportsForTest;

assert.equal(MAX_PROGRESS_SAMPLES, 120);
assert.equal(PROGRESS_SAMPLE_INTERVAL_MS, 1000);

const first = { observedAt: 1000, percent: 12, kind: 'input' };
let samples = appendProgressSample([], first);
assert.deepEqual(samples, [first]);

// 非有限值、越界读数或节流内的读数是同一数组引用，不产生新历史。
assert.equal(
  appendProgressSample(samples, { observedAt: 1500, percent: NaN, kind: 'input' }),
  samples,
);
assert.equal(
  appendProgressSample(samples, { observedAt: 1500, percent: -1, kind: 'input' }),
  samples,
);
assert.equal(
  appendProgressSample(samples, { observedAt: 1500, percent: 101, kind: 'input' }),
  samples,
);

// 1 秒内节流；达到间隔后记录。
const second = { observedAt: 1999, percent: 20, kind: 'input' };
assert.equal(appendProgressSample(samples, second), samples);
const third = { observedAt: 2000, percent: 20, kind: 'input' };
samples = appendProgressSample(samples, third);
assert.deepEqual(samples, [first, third]);

// 每秒最多一个样本，不同 kind 共享节流但保留输入/阶段两条序列。
const stageReading = { observedAt: 2500, percent: 42, kind: 'stage' };
assert.deepEqual(appendProgressSample(samples, stageReading), samples);
const stageNext = { observedAt: 3000, percent: 42, kind: 'stage' };
samples = appendProgressSample(samples, stageNext);
assert.deepEqual(samples, [first, third, stageNext]);

// 阶段结束：不足 1 秒也补最终读数，但相同读数不重复。
const finalWithinInterval = { observedAt: 3500, percent: 100, kind: 'stage' };
samples = appendProgressSample(samples, finalWithinInterval, { terminal: true });
assert.deepEqual(samples, [first, third, stageNext, finalWithinInterval]);
assert.deepEqual(
  appendProgressSample(samples, { observedAt: 3600, percent: 100, kind: 'stage' }, { terminal: true }),
  samples,
);

// 阶段结束但最终读数与上一条 kind 不同，允许记录。
const inputFinal = { observedAt: 3600, percent: 100, kind: 'input' };
samples = appendProgressSample(samples, inputFinal, { terminal: true });
assert.deepEqual(samples.at(-1), inputFinal);

// 数量上限只保留最近的样本。
const bounded = appendProgressSample(
  [],
  { observedAt: 0, percent: 0, kind: 'stage' },
);
let many = bounded;
for (let i = 1; i <= 130; i += 1) {
  many = appendProgressSample(many, {
    observedAt: i * 1000,
    percent: i % 101,
    kind: 'stage',
  });
}
assert.equal(many.length, 120);
assert.equal(many[0].observedAt, 11000);
assert.equal(many.at(-1).observedAt, 130000);
const customLimit = appendProgressSample(
  [
    { observedAt: 0, percent: 1, kind: 'stage' },
    { observedAt: 1000, percent: 2, kind: 'stage' },
    { observedAt: 2000, percent: 3, kind: 'stage' },
  ],
  { observedAt: 3000, percent: 4, kind: 'stage' },
  { limit: 2 },
);
assert.equal(customLimit.length, 2);
assert.deepEqual(customLimit.map((sample) => sample.percent), [3, 4]);

console.log('Progress history sampling: passed');
