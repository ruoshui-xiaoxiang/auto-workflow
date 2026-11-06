// 星图左上角的数据流面板：持有唯一的 job SSE，向星图广播事件。
import {
  initial, reduce, statusLabel, elapsedText, shotStats, STAGES, TERMINAL
} from '/live_panel_model.js';

const COLLAPSE_KEY = 'fanxing.flow.collapsed';

let state = initial();
let es = null;
let pollTimer = null;
let watchedId = '';
let manualCollapsed = false;

const $ = (id) => document.getElementById(id);

function setCollapsed(on) {
  const collapsed = !!on;
  document.body.classList.toggle('rail-collapsed', collapsed);
  const panel = $('flow-panel');
  if (panel) panel.classList.toggle('collapsed', collapsed);
  window.dispatchEvent(new CustomEvent('fanxing:rail', {
    detail: { collapsed }
  }));
}

function panelEls() {
  const panel = $('flow-panel');
  if (!panel) return null;
  return {
    panel,
    body: $('flow-body'),
    toggle: $('flow-toggle'),
    state: $('flow-state'),
    dot: $('flow-dot'),
    stages: $('flow-stages'),
    now: $('flow-now'),
    log: $('flow-log'),
    railTab: $('rail-tab'),
    railDot: $('rail-dot'),
    railText: $('rail-text')
  };
}

function fmtDur(sec) {
  if (sec == null) return '';
  if (sec < 60) return sec.toFixed(1).replace(/\.0$/, '') + 's';
  return Math.floor(sec / 60) + 'm' + String(Math.round(sec % 60)).padStart(2, '0') + 's';
}

function renderStage(id, meta, els) {
  const row = document.createElement('div');
  row.className = 'flow-stage st-' + (meta.status || 'pending');
  const dot = document.createElement('i');
  const label = document.createElement('span');
  label.className = 'flow-stage-label';
  label.textContent = (STAGES.find((s) => s.id === id) || {}).label || id;
  const sub = document.createElement('em');
  sub.className = 'flow-stage-sub';
  sub.textContent = meta.duration_s != null ? fmtDur(meta.duration_s)
    : (meta.status === 'running' ? '进行中' : (meta.status === 'skipped' ? '跳过' : ''));
  row.appendChild(dot);
  row.appendChild(label);
  row.appendChild(sub);
  if (meta.summary) row.title = meta.summary;
  return row;
}

function render() {
  const els = panelEls();
  if (!els) return;
  const st = state.status || 'idle';
  els.dot.className = 'flow-dot st-' + st;
  const elapsed = elapsedText(state);
  els.state.textContent = statusLabel(state) + (elapsed ? ' · ' + elapsed : '');
  if (els.railDot) els.railDot.className = 'flow-dot st-' + st;
  if (els.railText) {
    const brief = state.currentShot
      ? statusLabel(state) + ' · ' + state.currentShot
      : statusLabel(state);
    els.railText.textContent = '数据流 · ' + brief;
  }

  els.stages.textContent = '';
  STAGES.forEach((s) => els.stages.appendChild(renderStage(s.id, state.stages[s.id], els)));

  const stats = shotStats(state);
  let now = '';
  if (state.currentShot) {
    const labels = { running: '运行中', waiting: '等待中', done: '完成', failed: '失败' };
    now = state.currentShot + ' · ' + (labels[state.currentState] || state.currentState || '');
    if (state.elapsed_s != null) now += ' · 已等 ' + Math.round(state.elapsed_s / 60) + ' 分钟';
    if (state.videos != null) now += ' · ' + state.videos + ' 个视频';
  } else if (stats.total) {
    now = '整批 ' + stats.total + ' 镜';
    if (stats.pass || stats.block) now += ' · 通过 ' + stats.pass + ' / 阻断 ' + stats.block;
  }
  if (st === 'idle') now = '等待任务';
  els.now.textContent = now;
  els.now.className = 'flow-now' + (stats.block ? ' bad' : '');
  els.log.textContent = state.logs.join('\n');
  els.log.scrollTop = els.log.scrollHeight;
}

function broadcast(ev) {
  window.dispatchEvent(new CustomEvent('fanxing:job', { detail: ev }));
}

function broadcastSnapshot() {
  window.dispatchEvent(new CustomEvent('fanxing:snapshot', {
    detail: { shots: Object.assign({}, state.shotStates), status: state.status,
              jobId: state.jobId, currentShot: state.currentShot }
  }));
}

function apply(ev, silent) {
  if (!ev || typeof ev !== 'object') return;
  if (ev.type === 'job' ||
      (ev.type === 'status' && ['queued', 'gating', 'running'].includes(ev.status))) {
    // 任务一来就展开；用户手动收起后，后续日志不会反复弹开。
    manualCollapsed = false;
    setCollapsed(false);
  }
  state = reduce(state, ev);
  render();
  if (!silent) broadcast(ev);
}

function hydrate(job) {
  state = initial();
  const events = Array.isArray(job && job.events) ? job.events : [];
  if (events.length) {
    events.forEach((ev) => apply(ev, true));
  } else if (job) {
    // 兼容没有 events 的旧任务：至少把状态和日志补出来。
    apply({ type: 'job', job_id: job.job_id, shots: job.shots || [],
            stage: job.stage || '', started_at: job.started_at, at: job.started_at }, true);
    apply({ type: 'status', status: job.status, ended_at: job.ended_at }, true);
    (job.log || []).forEach((line) => apply({ type: 'log', line }, true));
  }
  render();
  broadcastSnapshot();
}

function closeLive() {
  if (es) { try { es.close(); } catch (_) { /* ignore */ } es = null; }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function fetchJob(jobId) {
  const r = await fetch('/api/canvas/jobs/' + encodeURIComponent(jobId), { cache: 'no-store' });
  if (!r.ok) throw new Error('job HTTP ' + r.status);
  return r.json();
}

function isTerminal() {
  return TERMINAL.has(state.status);
}

function startPolling(jobId) {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    try {
      const job = await fetchJob(jobId);
      if (job.error) return;
      if ((job.events || []).length) {
        // 轮询是兜底通道：用完整事件重放，避免漏事件后状态错位。
        hydrate(job);
      } else {
        apply({ type: 'status', status: job.status, ended_at: job.ended_at });
      }
      if (TERMINAL.has(job.status)) closeLive();
    } catch (_) { /* 下一轮再试 */ }
  }, 2000);
}

function connect(jobId) {
  closeLive();
  try {
    es = new EventSource('/api/canvas/jobs/' + encodeURIComponent(jobId) + '/events');
    es.onmessage = (msg) => {
      let ev = null;
      try { ev = JSON.parse(msg.data || '{}'); } catch (_) { return; }
      if (!ev || typeof ev !== 'object') return;
      apply(ev, false);
      if (ev.type === 'status' && TERMINAL.has(ev.status)) {
        // 任务可能在 SSE 建连前就结束：以服务端完整事件为准再收口一次。
        fetchJob(jobId).then(hydrate).catch(() => {}).finally(closeLive);
      }
    };
    es.onerror = () => {
      if (isTerminal()) { closeLive(); return; }
      closeLive();
      startPolling(jobId);
    };
  } catch (_) {
    startPolling(jobId);
  }
}

async function watch(jobId) {
  if (!jobId) return;
  watchedId = jobId;
  closeLive();
  try {
    const job = await fetchJob(jobId);
    hydrate(job);
    if (!TERMINAL.has(job.status)) connect(jobId);
  } catch (_) {
    startPolling(jobId);
  }
}

async function boot() {
  const els = panelEls();
  if (!els) return;
  manualCollapsed = localStorage.getItem(COLLAPSE_KEY) === '1';
  setCollapsed(manualCollapsed);
  els.toggle.onclick = () => {
    manualCollapsed = !document.body.classList.contains('rail-collapsed');
    setCollapsed(manualCollapsed);
    localStorage.setItem(COLLAPSE_KEY, manualCollapsed ? '1' : '0');
  };
  if (els.railTab) {
    els.railTab.onclick = () => {
      manualCollapsed = false;
      setCollapsed(false);
      localStorage.setItem(COLLAPSE_KEY, '0');
    };
  }
  render();
  // 事件之间也走秒：顶部已用时间不能等到下一条日志才跳。
  setInterval(() => {
    if (['queued', 'gating', 'running'].includes(state.status)) render();
  }, 1000);
  try {
    const r = await fetch('/api/canvas/jobs', { cache: 'no-store' });
    const d = await r.json();
    const job = d.active || (d.recent || [])[0];
    if (!job) {
      // 没有任务时只留标题条，把视线还给星图。
      setCollapsed(true);
      return;
    }
    hydrate(job);
    if (d.active) {
      setCollapsed(false);
      connect(job.job_id);
    }
  } catch (_) { /* 没任务也能用 */ }
}

window.__fanxingLive = {
  watch,
  toggle() {
    const next = !document.body.classList.contains('rail-collapsed');
    manualCollapsed = next;
    setCollapsed(next);
    localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0');
    return next;
  },
  isCollapsed() {
    return document.body.classList.contains('rail-collapsed');
  },
  snapshot() {
    return { shots: Object.assign({}, state.shotStates), status: state.status,
             jobId: state.jobId, currentShot: state.currentShot };
  },
  state() { return state; },
  jobId() { return watchedId || state.jobId; }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
