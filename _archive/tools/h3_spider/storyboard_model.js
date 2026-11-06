// 分镜画布的纯逻辑：不 import three，也不碰 DOM，方便 node --test 直接跑。
// map3d.js 在 canvas 模式下动态 import 这里的 buildStoryboardModel。

export function snap(v, step = 0.5) {
  return Math.round(v / step) * step;
}

export function ringLayout(ids, center = [0, 0, 0], radius = 5.5) {
  return ids.map((id, i) => {
    const a = (i / Math.max(1, ids.length)) * Math.PI * 2;
    return { id, pos: [center[0] + Math.cos(a) * radius, center[1], center[2] + Math.sin(a) * radius] };
  });
}

export function buildStoryboardModel(payload) {
  const shots = payload.shots || [];
  const anchors = payload.anchors || [];
  const nodes = [];
  shots.forEach((s, i) => {
    nodes.push({
      id: s.id, kind: 'node', label: s.id,
      sub: payload.status?.[s.id] || '未检',
      color: payload.status?.[s.id] === 'PASS' ? 0x3ddc97
        : payload.status?.[s.id] === 'BLOCK' ? 0xff6b6b : 0x7f909f,
      status: payload.status?.[s.id] === 'PASS' ? 'pass'
        : payload.status?.[s.id] === 'BLOCK' ? 'block' : 'muted',
      baseSize: 0.56, sizeMul: 1.0, shot: s, ringIndex: i % 3,
      rows: [['时长', s.duration], ['mode', s.mode], ['QC', payload.status?.[s.id] || '未检']]
    });
  });
  anchors.forEach((a) => {
    nodes.push({
      id: a.id, kind: 'anchor', label: a.label, sub: a.kind,
      color: a.kind === 'cast' ? 0xf5b955 : 0x38bdf8, status: 'ok',
      baseSize: 0.34, sizeMul: 0.8, anchor: a, ringIndex: 2,
      rows: [['类型', a.kind]]
    });
  });
  return {
    overall: 'CANVAS', passCount: 0, shotCount: shots.length,
    systems: [{
      id: 'storyboard', kind: 'system', label: '分镜带', fullLabel: '分镜星带', sub: `${shots.length} 镜`,
      color: 0x5eead4, center: [0, -3.5, 22], rings: [4.3, 6.2, 8.1],
      tilt: [0.30, -0.22], nodes
    }],
    shots: nodes.filter((n) => n.kind === 'node'),
    anchors: nodes.filter((n) => n.kind === 'anchor'),
    edges: payload.edges || [], canvas: payload.canvas || {},
    legs: [], slots: [], evidence: [], failures: 0, batchDir: payload.batch_dir || ''
  };
}

// 屏幕框选：rect 约定为左上角 + 非负宽高（拖拽时调用方用 Math.min/Math.abs 归一）。
// 负宽高不做镜像纠正，直接落空。边界点算选中。
export function screenRectSelect(points, rect) {
  const x2 = rect.x + rect.w;
  const y2 = rect.y + rect.h;
  return points
    .filter((p) => p.x >= rect.x && p.x <= x2 && p.y >= rect.y && p.y <= y2)
    .map((p) => p.id);
}

const EDGE_KEY_TYPES = Object.freeze({ '1': 'order', '2': 'chain', '3': 'ref' });

// 键盘 1/2/3 切换新建边的类型；键值来自浏览器 e.key，非字符串一律视为无效。
// 用 hasOwn 挡住 toString/constructor 之类的原型链键。
export function edgeTypeForKey(key) {
  return typeof key === 'string' && Object.hasOwn(EDGE_KEY_TYPES, key)
    ? EDGE_KEY_TYPES[key] : null;
}

// 撤销栈：push 即执行 redo；超过 limit 丢最旧的一条；push 会清空 redo 分支。
export class CommandStack {
  constructor(limit = 50) {
    this.limit = limit;
    this.done = [];
    this.undone = [];
  }
  push(cmd) {
    cmd.redo();
    this.done.push(cmd);
    if (this.done.length > this.limit) this.done.shift();
    this.undone = [];
  }
  undo() {
    const cmd = this.done.pop();
    if (!cmd) return false;
    cmd.undo();
    this.undone.push(cmd);
    return true;
  }
  redo() {
    const cmd = this.undone.pop();
    if (!cmd) return false;
    cmd.redo();
    this.done.push(cmd);
    return true;
  }
}
