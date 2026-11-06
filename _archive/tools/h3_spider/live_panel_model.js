// 数据流面板的纯状态归约：不碰 DOM，node --test 可直接跑。

export const STAGES = [
  { id: 'precheck', label: '预检' },
  { id: 'build', label: '建稿' },
  { id: 'qc', label: '质检' },
  { id: 'gate', label: '跑前闸' },
  { id: 'run', label: '出片' }
];

export const TERMINAL = new Set([
  'done', 'failed', 'cancelled', 'gate_blocked', 'interrupted'
]);

const STAGE_IDS = new Set(STAGES.map((s) => s.id));

function emptyStages() {
  const out = {};
  STAGES.forEach((s) => {
    out[s.id] = { status: 'pending', duration_s: null, summary: null, reason: null };
  });
  return out;
}

export function initial() {
  return {
    status: 'idle',
    jobId: '',
    shots: [],
    stage: '',
    startedAt: null,
    endedAt: null,
    lastEventAt: null,
    currentShot: '',
    currentState: '',
    elapsed_s: null,
    videos: null,
    stages: emptyStages(),
    shotStates: {},
    logs: []
  };
}

export function reduce(state, ev) {
  if (!ev || typeof ev !== 'object') return state;
  const next = Object.assign({}, state, {
    stages: Object.assign({}, state.stages),
    shotStates: Object.assign({}, state.shotStates),
    logs: state.logs.slice()
  });
  if (ev.at) next.lastEventAt = ev.at;

  switch (ev.type) {
    case 'job': {
      const fresh = initial();
      fresh.status = 'queued';
      fresh.jobId = ev.job_id || '';
      fresh.shots = Array.isArray(ev.shots) ? ev.shots.slice() : [];
      fresh.stage = ev.stage || '';
      fresh.startedAt = ev.started_at || ev.at || Date.now() / 1000;
      fresh.lastEventAt = ev.at || null;
      return fresh;
    }
    case 'status': {
      if (ev.status) next.status = ev.status;
      if (ev.ended_at) next.endedAt = ev.ended_at;
      if (TERMINAL.has(next.status) && !next.endedAt) {
        next.endedAt = ev.at || Date.now() / 1000;
      }
      return next;
    }
    case 'stage': {
      if (!STAGE_IDS.has(ev.stage)) return next;
      const prev = next.stages[ev.stage];
      // 跳过事件不能覆盖已经跑完的结果；但 JobManager 接管出片时
      // run 会从 skipped 重新进入 running，这种情况要允许。
      if (ev.status === 'skipped' && ['ok', 'block', 'error'].includes(prev.status)) {
        return next;
      }
      next.stages[ev.stage] = {
        status: ev.status || 'pending',
        duration_s: ev.duration_s == null ? prev.duration_s : ev.duration_s,
        summary: ev.summary == null ? prev.summary : ev.summary,
        reason: ev.reason == null ? prev.reason : ev.reason
      };
      return next;
    }
    case 'shot': {
      if (!ev.shot) return next;
      const st = ev.state || 'running';
      next.shotStates[ev.shot] = st;
      // 质检是按批给结果的，不把它当成“当前镜头”；出片才逐镜推进。
      if (ev.source === 'qc' && (st === 'pass' || st === 'block')) {
        next.currentShot = '';
        next.currentState = '';
        next.elapsed_s = null;
        next.videos = null;
      } else if (ev.source === 'run' || st === 'running') {
        next.currentShot = ev.shot;
        next.currentState = st;
        if (ev.elapsed_s != null) next.elapsed_s = ev.elapsed_s;
        if (ev.videos != null) next.videos = ev.videos;
      }
      return next;
    }
    case 'log': {
      if (ev.line) {
        next.logs.push(String(ev.line));
        if (next.logs.length > 5) next.logs = next.logs.slice(-5);
      }
      return next;
    }
    default:
      return next;
  }
}

export function nodeState(shotState) {
  if (shotState === 'done' || shotState === 'pass') return 'done';
  if (shotState === 'failed' || shotState === 'block') return 'fail';
  if (shotState === 'running' || shotState === 'waiting') return 'running';
  return '';
}

export function statusLabel(state) {
  if (!state || state.status === 'idle') return '待命';
  const running = STAGES.find((s) => state.stages[s.id].status === 'running');
  switch (state.status) {
    case 'queued': return '排队中';
    case 'gating': return running ? running.label + '中' : '闸门中';
    case 'running': return '出片中';
    case 'done': return '完成';
    case 'gate_blocked': return '已阻断';
    case 'failed': return '失败';
    case 'cancelled': return '已取消';
    case 'interrupted': return '已中断';
    default: return state.status;
  }
}

export function elapsedText(state, now) {
  if (!state || !state.startedAt) return '';
  const end = state.endedAt || (now == null ? Date.now() / 1000 : now);
  const sec = Math.max(0, Math.round(end - state.startedAt));
  if (sec < 60) return sec + 's';
  const mins = Math.floor(sec / 60);
  const rest = sec % 60;
  return mins + '分' + String(rest).padStart(2, '0') + '秒';
}

export function shotStats(state) {
  const out = { pass: 0, block: 0, running: 0, total: (state.shots || []).length };
  Object.values(state.shotStates || {}).forEach((s) => {
    if (s === 'pass' || s === 'done') out.pass += 1;
    else if (s === 'block' || s === 'failed') out.block += 1;
    else if (s === 'running' || s === 'waiting') out.running += 1;
  });
  return out;
}
