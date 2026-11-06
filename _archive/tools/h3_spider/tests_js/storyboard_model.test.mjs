import test from 'node:test';
import assert from 'node:assert/strict';
import {
  snap, ringLayout, buildStoryboardModel,
  screenRectSelect, edgeTypeForKey, CommandStack
} from '../storyboard_model.js';

test('snap rounds to half unit', () => {
  assert.equal(snap(1.24), 1.0);
  assert.equal(snap(1.26), 1.5);
});

test('ringLayout places all ids', () => {
  const out = ringLayout(['U01', 'U02', 'U03'], [0, 0, 0], 5);
  assert.equal(out.length, 3);
  assert.ok(Math.abs(Math.hypot(out[0].pos[0], out[0].pos[2]) - 5) < 1e-6);
});

test('buildStoryboardModel marks PASS green', () => {
  const m = buildStoryboardModel({
    shots: [{ id: 'U01', duration: 8 }],
    status: { U01: 'PASS' }, anchors: [], edges: [], canvas: {}
  });
  assert.equal(m.systems[0].nodes[0].color, 0x3ddc97);
  assert.equal(m.systems[0].nodes[0].sub, 'PASS');
});

test('buildStoryboardModel marks BLOCK red and keeps QC row', () => {
  const m = buildStoryboardModel({
    shots: [{ id: 'U01', duration: 8, mode: 'f2v' }],
    status: { U01: 'BLOCK' }, anchors: [], edges: [], canvas: {}
  });
  const n = m.systems[0].nodes[0];
  assert.equal(n.color, 0xff6b6b);
  assert.equal(n.status, 'block');
  assert.equal(n.sub, 'BLOCK');
  assert.deepEqual(n.rows, [['时长', 8], ['mode', 'f2v'], ['QC', 'BLOCK']]);
});

test('buildStoryboardModel renders missing status as muted 未检', () => {
  const withEmpty = buildStoryboardModel({
    shots: [{ id: 'U01', duration: 8 }],
    status: {}, anchors: [], edges: [], canvas: {}
  });
  const withoutStatus = buildStoryboardModel({
    shots: [{ id: 'U01', duration: 8 }],
    anchors: [], edges: [], canvas: {}
  });
  for (const m of [withEmpty, withoutStatus]) {
    const n = m.systems[0].nodes[0];
    assert.equal(n.color, 0x7f909f);
    assert.equal(n.status, 'muted');
    assert.equal(n.sub, '未检');
    assert.deepEqual(n.rows[2], ['QC', '未检']);
  }
});

test('buildStoryboardModel colors anchors by kind', () => {
  const m = buildStoryboardModel({
    shots: [{ id: 'U01', duration: 8 }],
    status: { U01: 'PASS' },
    anchors: [
      { id: 'A1', label: '阿澈', kind: 'cast' },
      { id: 'A2', label: '巷道', kind: 'scene' }
    ],
    edges: [], canvas: {}
  });
  const cast = m.systems[0].nodes.find((n) => n.id === 'A1');
  const scene = m.systems[0].nodes.find((n) => n.id === 'A2');
  assert.equal(cast.kind, 'anchor');
  assert.equal(cast.color, 0xf5b955);
  assert.equal(cast.sub, 'cast');
  assert.equal(cast.status, 'ok');
  assert.equal(cast.label, '阿澈');
  assert.deepEqual(cast.rows, [['类型', 'cast']]);
  assert.equal(scene.color, 0x38bdf8);
  assert.equal(m.anchors.length, 2);
  assert.equal(m.shots.length, 1);
  assert.deepEqual(m.shots.map((n) => n.id), ['U01']);
});

test('buildStoryboardModel keeps edges, canvas, shot count and ring order', () => {
  const edges = [{ id: 'e1', from: 'U01', to: 'U02', type: 'order' }];
  const canvas = { project: 'demo', nodes: { U01: { pos: [1, 0, 2] } } };
  const m = buildStoryboardModel({
    shots: [
      { id: 'U01', duration: 8 }, { id: 'U02', duration: 5 },
      { id: 'U03', duration: 3 }, { id: 'U04', duration: 6 }
    ],
    status: { U01: 'PASS', U02: 'BLOCK' },
    anchors: [], edges, canvas
  });
  assert.deepEqual(m.edges, edges);
  assert.deepEqual(m.canvas, canvas);
  assert.equal(m.shotCount, 4);
  assert.equal(m.overall, 'CANVAS');
  assert.equal(m.systems[0].sub, '4 镜');
  assert.equal(m.systems[0].id, 'storyboard');
  assert.deepEqual(m.shots.map((n) => n.ringIndex), [0, 1, 2, 0]);
});

test('buildStoryboardModel tolerates an empty payload', () => {
  const m = buildStoryboardModel({});
  assert.equal(m.shotCount, 0);
  assert.deepEqual(m.systems[0].nodes, []);
  assert.deepEqual(m.edges, []);
  assert.deepEqual(m.canvas, {});
  assert.equal(m.batchDir, '');
  assert.equal(buildStoryboardModel({ batch_dir: 'D:/x/batch' }).batchDir, 'D:/x/batch');
});

test('screenRectSelect picks points inside rect', () => {
  const pts = [
    { id: 'a', x: 10, y: 10 },
    { id: 'b', x: 200, y: 200 },
  ];
  assert.deepEqual(screenRectSelect(pts, { x: 0, y: 0, w: 50, h: 50 }), ['a']);
});

test('screenRectSelect includes boundary points', () => {
  const pts = [
    { id: 'origin', x: 0, y: 0 },
    { id: 'far-corner', x: 50, y: 50 },
    { id: 'inside', x: 25, y: 40 },
    { id: 'outside-x', x: 50.01, y: 25 },
    { id: 'outside-y', x: 25, y: 50.01 }
  ];
  assert.deepEqual(screenRectSelect(pts, { x: 0, y: 0, w: 50, h: 50 }),
    ['origin', 'far-corner', 'inside']);
  assert.deepEqual(screenRectSelect([], { x: 0, y: 0, w: 50, h: 50 }), []);
});

test('screenRectSelect assumes w/h >= 0: a negative-size rect selects nothing', () => {
  // 框选调用方负责归一成左上角 + 正尺寸（见 map3d 里 Math.min/Math.abs），
  // 这里不做镜像纠正，负尺寸直接落空。
  const pts = [{ id: 'a', x: 25, y: 25 }];
  assert.deepEqual(screenRectSelect(pts, { x: 50, y: 50, w: -50, h: -50 }), []);
});

test('edgeTypeForKey maps 1/2/3', () => {
  assert.equal(edgeTypeForKey('1'), 'order');
  assert.equal(edgeTypeForKey('2'), 'chain');
  assert.equal(edgeTypeForKey('3'), 'ref');
  assert.equal(edgeTypeForKey('x'), null);
});

test('edgeTypeForKey returns null for unmapped and inherited keys', () => {
  for (const key of ['0', '4', '', 'Enter', undefined, null, 1,
    'toString', 'constructor', '__proto__']) {
    assert.equal(edgeTypeForKey(key), null);
  }
});

test('command stack undo redo', () => {
  const s = new CommandStack(3);
  let v = 0;
  s.push({ redo: () => { v = 1; }, undo: () => { v = 0; } });
  s.push({ redo: () => { v = 2; }, undo: () => { v = 1; } });
  s.undo(); assert.equal(v, 1);
  s.undo(); assert.equal(v, 0);
  s.redo(); assert.equal(v, 1);
});

test('command stack defaults to a 50 command limit', () => {
  assert.equal(new CommandStack().limit, 50);
});

test('command stack drops the oldest command past the limit', () => {
  const s = new CommandStack(3);
  const log = [];
  for (let i = 1; i <= 4; i += 1) {
    s.push({ redo: () => log.push('redo-' + i), undo: () => log.push('undo-' + i) });
  }
  assert.deepEqual(log, ['redo-1', 'redo-2', 'redo-3', 'redo-4']);
  assert.equal(s.done.length, 3);
  assert.equal(s.undo(), true);
  assert.equal(s.undo(), true);
  assert.equal(s.undo(), true);
  assert.equal(s.undo(), false);
  assert.deepEqual(log.slice(4), ['undo-4', 'undo-3', 'undo-2']);
});

test('command stack push clears the redo branch', () => {
  const s = new CommandStack();
  let v = 0;
  s.push({ redo: () => { v = 1; }, undo: () => { v = 0; } });
  s.push({ redo: () => { v = 2; }, undo: () => { v = 1; } });
  s.undo();
  s.push({ redo: () => { v = 9; }, undo: () => { v = 1; } });
  assert.equal(v, 9);
  assert.deepEqual(s.undone, []);
  assert.equal(s.redo(), false);
});

test('command stack undo/redo on an empty stack return false', () => {
  const s = new CommandStack();
  assert.equal(s.undo(), false);
  assert.equal(s.redo(), false);
});

test('command stack redo replays in push order', () => {
  const s = new CommandStack();
  const log = [];
  ['a', 'b', 'c'].forEach((k) => s.push({
    redo: () => log.push('redo-' + k), undo: () => log.push('undo-' + k)
  }));
  s.undo(); s.undo(); s.undo();
  assert.deepEqual(log, ['redo-a', 'redo-b', 'redo-c',
    'undo-c', 'undo-b', 'undo-a']);
  assert.equal(s.redo(), true);
  assert.equal(s.redo(), true);
  assert.equal(s.redo(), true);
  assert.equal(s.redo(), false);
  assert.deepEqual(log.slice(6), ['redo-a', 'redo-b', 'redo-c']);
});
