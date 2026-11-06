import test from 'node:test';
import assert from 'node:assert/strict';
import {
  initial, reduce, nodeState, statusLabel, shotStats
} from '../live_panel_model.js';

function stage(state, id, status, extra) {
  return reduce(state, Object.assign({ type: 'stage', stage: id, status }, extra || {}));
}

test('job resets state and seeds shots', () => {
  let s = reduce(initial(), {
    type: 'job', job_id: 'j1', shots: ['U01', 'U02'], stage: 'run', started_at: 100
  });
  assert.equal(s.jobId, 'j1');
  assert.deepEqual(s.shots, ['U01', 'U02']);
  assert.equal(s.status, 'queued');
  assert.equal(s.stages.qc.status, 'pending');
});

test('stage running then ok keeps duration', () => {
  let s = reduce(initial(), { type: 'job', job_id: 'j1', shots: ['U01'], started_at: 1 });
  s = reduce(s, { type: 'status', status: 'gating' });
  s = stage(s, 'qc', 'running');
  assert.equal(s.stages.qc.status, 'running');
  assert.equal(statusLabel(s), '质检中');
  s = stage(s, 'qc', 'ok', { duration_s: 3.2, summary: 'PASS · 1 镜' });
  assert.equal(s.stages.qc.status, 'ok');
  assert.equal(s.stages.qc.duration_s, 3.2);
  assert.equal(s.stages.qc.summary, 'PASS · 1 镜');
});

test('skipped never overwrites a finished stage', () => {
  let s = reduce(initial(), { type: 'job', job_id: 'j1', shots: ['U01'], started_at: 1 });
  s = stage(s, 'gate', 'ok');
  s = stage(s, 'gate', 'skipped', { reason: '上游 BLOCK' });
  assert.equal(s.stages.gate.status, 'ok');
});

test('run can leave skipped and enter running', () => {
  let s = reduce(initial(), { type: 'job', job_id: 'j1', shots: ['U01'], started_at: 1 });
  s = reduce(s, { type: 'status', status: 'gating' });
  s = stage(s, 'run', 'skipped', { reason: '未显式 --execute-run' });
  assert.equal(s.stages.run.status, 'skipped');
  s = stage(s, 'run', 'running');
  assert.equal(s.stages.run.status, 'running');
  assert.equal(statusLabel(s), '出片中');
});

test('qc shot results do not steal current shot', () => {
  let s = reduce(initial(), { type: 'job', job_id: 'j1', shots: ['U01'], started_at: 1 });
  s = reduce(s, { type: 'shot', shot: 'U01', state: 'running', source: 'qc' });
  assert.equal(s.currentShot, 'U01');
  s = reduce(s, { type: 'shot', shot: 'U01', state: 'pass', source: 'qc' });
  assert.equal(s.shotStates.U01, 'pass');
  assert.equal(s.currentShot, '');
  assert.equal(nodeState(s.shotStates.U01), 'done');
});

test('run shot events drive current shot and elapsed', () => {
  let s = reduce(initial(), { type: 'job', job_id: 'j1', shots: ['U01', 'U02'], started_at: 1 });
  s = reduce(s, { type: 'shot', shot: 'U02', state: 'running', source: 'run' });
  s = reduce(s, { type: 'shot', shot: 'U02', state: 'waiting', source: 'run', elapsed_s: 240 });
  assert.equal(s.currentShot, 'U02');
  assert.equal(s.elapsed_s, 240);
  s = reduce(s, { type: 'shot', shot: 'U02', state: 'done', source: 'run', videos: 2 });
  assert.equal(nodeState(s.shotStates.U02), 'done');
  assert.equal(s.videos, 2);
});

test('logs keep last five lines', () => {
  let s = initial();
  for (let i = 0; i < 8; i += 1) {
    s = reduce(s, { type: 'log', line: 'L' + i });
  }
  assert.deepEqual(s.logs, ['L3', 'L4', 'L5', 'L6', 'L7']);
});

test('terminal status stamps endedAt and stats aggregate', () => {
  let s = reduce(initial(), { type: 'job', job_id: 'j1', shots: ['U01', 'U02'], started_at: 100 });
  s = reduce(s, { type: 'shot', shot: 'U01', state: 'pass', source: 'qc' });
  s = reduce(s, { type: 'shot', shot: 'U02', state: 'block', source: 'qc' });
  s = reduce(s, { type: 'status', status: 'gate_blocked', at: 130 });
  assert.equal(s.endedAt, 130);
  assert.equal(statusLabel(s), '已阻断');
  assert.deepEqual(shotStats(s), { pass: 1, block: 1, running: 0, total: 2 });
});

test('nodeState maps all shot states', () => {
  assert.equal(nodeState('running'), 'running');
  assert.equal(nodeState('waiting'), 'running');
  assert.equal(nodeState('pass'), 'done');
  assert.equal(nodeState('done'), 'done');
  assert.equal(nodeState('block'), 'fail');
  assert.equal(nodeState('failed'), 'fail');
  assert.equal(nodeState(''), '');
});
