// 分镜画布：镜头/锚点落点、三种线型、右侧镜头卡。
// 依赖 map3d.js 在 canvas 模式暴露的 window.__fanxingMap；纯布局/几何逻辑留在
// storyboard_model.js，这里只碰 three 场景、DOM 与画布数据。

import {
  ringLayout, snap, screenRectSelect, edgeTypeForKey, CommandStack
} from './storyboard_model.js';

const CARD_ID = 'sb-card';
// 与 storyboard_model.buildStoryboardModel 里画布星系的 center 保持一致
const CENTER = [0, -3.5, 22];
const SHOT_RING = 5.5;
// 锚点环 7.0：默认画布机位 (0,26,12)、中心 (0,-3.5,22) 下，最远锚点约 33.8u，
// 落在 map3d 标签 LOD 的 34u 以内；8.4 会顶到 34.4u 把远端标签藏掉。
const ANCHOR_RING = 7.0;
const LABEL_LIFT = 0.62;

// 卡片底部一行操作提示：连线的方向语义（尤其 ref）在这里也能查到。
const CARD_NOTE =
  '<div class="sb-note">拖动节点改布局 · 从出线口拖到目标节点连线（1 order / 2 chain / 3 ref）' +
  ' · 双击边删除 · 右键边换线型 · Ctrl+Z 撤销<br>' +
  'ref：起点 = 引用方（consumer），落点 = 参考源（source）</div>';

const EDGE_STYLE = {
  order: { color: 0xbfe9ff, opacity: 0.75, dashed: false },
  chain: { color: 0xf5b955, opacity: 0.9, dashed: true, dash: 0.45, gap: 0.3 },
  ref: { color: 0x5eead4, opacity: 0.45, dashed: true, dash: 0.45, gap: 0.18 }
};

const state = {
  map: null, data: null, nodes: new Map(), edgeObjs: [], group: null,
  selected: new Set(), currentType: 'order', dragging: null, connecting: null,
  ready: false, started: false, edgeDirty: false,
  // Task 12/13：当前卡片、草稿与批注红点。
  currentShot: null, cardTab: 'content', drafts: {}, dirty: new Set(), issueDots: null,
  applying: false,
  // Task 11：编辑层（监听器、框选框、出线口、拖线预览）各自一份，重初始化时整组拆掉。
  editingBound: false, abort: null, marquee: null, overlay: null,
  ports: new Map(), portTexture: null, preview: null
};

const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// 任务结束状态；面板和旧轮询兜底共用。
const JOB_TERMINAL = ['done', 'failed', 'cancelled', 'gate_blocked', 'interrupted'];
let liveBound = false;

/* ---------------- 初始化 ---------------- */

export async function initStoryboard(project) {
  const map = window.__fanxingMap;
  // 主星图是唯一入口：镜头星系在这里接管，其它星系继续走质检交互。
  if (!map || (map.mode !== 'single' && map.mode !== 'canvas')) {
    console.warn('[fanxing] storyboard 未初始化：主星图钩子缺失');
    return false;
  }
  // 二次调用（项目切换、保存后刷新）走同一条路：先拆掉上一轮的组与帧钩子再重建，
  // 场景里始终只有一份节点/边。拆完数据重新拉，避免沿用旧项目的坐标。
  if (state.started) teardownStoryboard();
  state.map = map;

  const proj = project || map.project || '';
  try {
    const res = await fetch('/api/canvas?project=' + encodeURIComponent(proj), { cache: 'no-store' });
    if (!res.ok) throw new Error('画布数据 HTTP ' + res.status);
    const data = await res.json();
    if (!data || !Array.isArray(data.shots)) throw new Error('画布数据缺少 shots 数组');
    state.data = data;
  } catch (err) {
    console.error('[fanxing] 画布数据加载失败', err);
    showErrorCard('画布数据加载失败', (err && err.message) || String(err), proj);
    return false;
  }
  state.data.anchors = state.data.anchors || [];
  state.data.edges = state.data.edges || [];
  state.data.status = state.data.status || {};

  buildNodes();
  buildEdges();
  // v2：布局改为按质量引力排布，旧的自由坐标不再沿用。
  const upgradedLayout = ((state.data.canvas || {}).layout_version || 1) < 2;
  state.data.canvas = state.data.canvas || {};
  state.data.canvas.layout_version = 2;
  if (upgradedLayout && state.data.project) saveLayout();
  map.onSelect = handleSelect;
  map.onFrame(update);
  state.ready = true;
  // 交互层只绑一次；initStoryboard 二次调用时 teardown 已经解绑过上一轮。
  try {
    bindEditing();
  } catch (err) {
    console.error('[fanxing] 编辑交互绑定失败', err);
  }
  try {
    syncIssueDots();
  } catch (err) {
    console.error('[fanxing] 批注红点初始化失败', err);
  }
  try {
    initToolbar();
  } catch (err) {
    console.error('[fanxing] 工具栏初始化失败', err);
  }
  window.__fanxingStoryboard = storyboardApi;
  return true;
}

/* ---------------- 拆除 / 二次初始化 ---------------- */

function teardownStoryboard() {
  unbindEditing();
  disposePorts();
  disposeEdges();
  if (state.group && state.map) state.map.scene.remove(state.group);
  state.group = null;
  state.nodes.clear();
  state.selected.clear();
  state.ready = false;
  state.edgeDirty = false;
  // 命令里握着的节点/边属于上一轮；重初始化后历史没有意义，整栈清掉。
  undo.done.length = 0;
  undo.undone.length = 0;
  if (state.map) {
    state.map.onSelect = null;
    // 上一轮 onFrame(update) 推进去的钩子要清掉，否则每帧会跑两份。
    if (Array.isArray(state.map.frameHooks)) state.map.frameHooks.length = 0;
  }
}

/* ---------------- 节点落点 ---------------- */

function ensureCanvasNodes() {
  if (!state.data.canvas || typeof state.data.canvas !== 'object') state.data.canvas = {};
  if (!state.data.canvas.nodes || typeof state.data.canvas.nodes !== 'object') {
    state.data.canvas.nodes = {};
  }
  return state.data.canvas.nodes;
}

function validPos(pos) {
  return Array.isArray(pos) && pos.length === 3
    && pos.every((v) => typeof v === 'number' && Number.isFinite(v));
}

// 缺省布局：镜头内环、锚点外环，各自按在组内的下标均分角度；只用于没有有效
// 存档坐标的节点，已存的坐标永远优先。
function storyboardCenter() {
  const model = window.__map && window.__map.model;
  const sys = model && (model.systems || []).find((s) => s.id === 'storyboard');
  return sys && sys.center ? [sys.center.x, sys.center.y, sys.center.z] : CENTER;
}

function defaultPositions() {
  const center = storyboardCenter();
  const shots = state.data.shots.map((s) => s.id);
  const anchors = (state.data.anchors || []).map((a) => a.id);
  const out = new Map();
  ringLayout(shots, center, SHOT_RING).forEach((x) => out.set(x.id, x.pos));
  ringLayout(anchors, center, ANCHOR_RING).forEach((x) => out.set(x.id, x.pos));
  return out;
}

// 只改 pos，pinned / note / selected_take 之类的记录字段原样保留。
function setSavedPos(saved, id, pos) {
  const entry = saved[id] || {};
  entry.pos = pos;
  saved[id] = entry;
  return entry;
}

function buildNodes() {
  const map = state.map;
  const { THREE } = map;
  const saved = ensureCanvasNodes();
  const defaults = defaultPositions();
  const useSaved = ((state.data.canvas || {}).layout_version || 1) >= 2;

  state.group = new THREE.Group();
  state.group.name = 'storyboard-edges';
  map.scene.add(state.group);
  state.started = true;

  map.nodeMeshes.forEach((mesh) => {
    const n = mesh.userData.pick;
    // 只接管镜头星系：质检腿/质检节点/主序星等不要被拖进镜头环。
    if (!n || !n.pos || (!n.shot && !n.anchor)) return;
    const entry = useSaved ? saved[n.id] : null;
    // 没有 v2 存档时直接用 map3d 按质量算好的轨道位置，不再重排成等距圆环。
    const pos = entry && validPos(entry.pos)
      ? entry.pos
      : (n.pos ? [n.pos.x, n.pos.y, n.pos.z] : defaults.get(n.id));
    if (validPos(pos)) {
      // 存档坐标留着不动；缺省落点写回去，Task 12 保存画布时可直接落盘。
      if (!entry || !validPos(entry.pos)) setSavedPos(saved, n.id, pos);
      n.pos.fromArray(pos);
      mesh.position.copy(n.pos);
      if (n.labelObj) n.labelObj.position.set(n.pos.x, n.pos.y + LABEL_LIFT, n.pos.z);
    }
    state.nodes.set(n.id, n);
  });
}

/* ---------------- 三种线型 ---------------- */

function edgePoints(a, b) {
  const { THREE } = state.map;
  const mid = a.clone().add(b).multiplyScalar(0.5);
  mid.y += 1.2;
  return new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(32);
}

function disposeEdges() {
  state.edgeObjs.forEach(({ line }) => {
    if (state.group) state.group.remove(line);
    line.geometry.dispose();
    line.material.dispose();
  });
  state.edgeObjs = [];
}

// 方向按数据原样画：order/chain 上游→下游，ref 消费方→参考源，不翻转。
function buildEdges() {
  const { THREE } = state.map;
  disposeEdges();
  let skipped = 0;
  (state.data.edges || []).forEach((e) => {
    if (!e || typeof e !== 'object') return;
    const a = state.nodes.get(e.from);
    const b = state.nodes.get(e.to);
    if (!a || !b) { skipped += 1; return; }
    const style = EDGE_STYLE[e.type] || EDGE_STYLE.order;
    const geo = new THREE.BufferGeometry().setFromPoints(edgePoints(a.pos, b.pos));
    const mat = style.dashed
      ? new THREE.LineDashedMaterial({
        color: style.color, transparent: true, opacity: style.opacity,
        dashSize: style.dash || 0.45, gapSize: style.gap || 0.3, depthWrite: false
      })
      : new THREE.LineBasicMaterial({
        color: style.color, transparent: true, opacity: style.opacity, depthWrite: false
      });
    const line = new THREE.Line(geo, mat);
    if (style.dashed) line.computeLineDistances();
    line.userData.edge = e;
    state.group.add(line);
    state.edgeObjs.push({ line, edge: e });
  });
  if (skipped) {
    console.warn('[fanxing] 画布里有 ' + skipped + ' 条边指向不存在的节点，已跳过');
  }
  // 新建的边已经按当下坐标生成，但下一帧统一重算一次最省心（也覆盖调用方
  // 复用旧边对象的情况）。
  state.edgeDirty = true;
}

/* ---------------- 每帧同步（Task 11 拖动时边跟随） ---------------- */

// 59 镜 × 58 条边 × 33 个点，每帧全量重算会把主线程吃干净；改成脏标记，
// 只有拖动/改布局时重建，其余帧直接返回。
export function markEdgeDirty() {
  state.edgeDirty = true;
}

function update() {
  if (!state.edgeDirty) return;
  state.edgeDirty = false;
  if (!state.edgeObjs.length) return;
  state.edgeObjs.forEach(({ line, edge }) => {
    const a = state.nodes.get(edge.from);
    const b = state.nodes.get(edge.to);
    if (!a || !b) return;
    line.geometry.setFromPoints(edgePoints(a.pos, b.pos));
    if (line.material.isLineDashedMaterial) line.computeLineDistances();
  });
}

/* ---------------- 选中 ---------------- */

// 主星图里镜头/锚点的高亮自己管，别去动质检星系的选中态。
// 选中可以是多选（Shift+点、框选），节点圆盘和 CSS2D 标签一起点亮。
function clearSelectionVisuals() {
  if (!state.map) return;
  state.nodes.forEach((n) => {
    const m = n.mesh;
    if (m && m.material && m.material.uniforms && m.material.uniforms.uSelected) {
      m.material.uniforms.uSelected.value = 0;
    }
    if (n.labelObj && n.labelObj.element) n.labelObj.element.classList.remove('sel');
  });
}

function paintSelection() {
  clearSelectionVisuals();
  state.selected.forEach((id) => {
    const n = state.nodes.get(id);
    if (!n) return;
    if (n.mesh && n.mesh.material && n.mesh.material.uniforms && n.mesh.material.uniforms.uSelected) {
      n.mesh.material.uniforms.uSelected.value = 1;
    }
    if (n.labelObj && n.labelObj.element) n.labelObj.element.classList.add('sel');
  });
}

function setSelection(ids) {
  state.selected.clear();
  (ids || []).forEach((id) => { if (state.nodes.has(id)) state.selected.add(id); });
  paintSelection();
}

// Shift+点：在现有集合里加/减一个节点，不换卡片。
function toggleSelection(id) {
  if (!state.nodes.has(id)) return 0;
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  paintSelection();
  return state.selected.size;
}

function clearSelection() {
  state.selected.clear();
  clearSelectionVisuals();
}

function closeCard() {
  const host = document.getElementById(CARD_ID);
  if (host) host.classList.remove('on');
}

function handleSelect(target) {
  if (!target || (target.kind !== 'node' && target.kind !== 'anchor')) {
    clearSelection();
    closeCard();
    return;
  }
  setSelection([target.id]);
  if (target.shot) renderCard(target.id);
  else renderAnchorCard(target);
}

/* ---------------- 右侧卡片 ---------------- */

function bindClose() {
  const host = document.getElementById(CARD_ID);
  const btn = host && host.querySelector('#sb-close');
  if (!btn) return;
  btn.onclick = () => {
    // 走 map3d 的 select(null)，onSelect 会把高亮和卡片一起收掉
    if (state.map && typeof state.map.select === 'function') state.map.select(null);
    else {
      clearSelection();
      host.classList.remove('on');
    }
  };
}

function assetUrl(path) {
  return '/api/canvas/asset?project=' + encodeURIComponent(state.data.project) +
    '&path=' + encodeURIComponent(path);
}

function getPath(obj, path) {
  let cur = obj;
  for (const k of String(path).split('.')) {
    if (cur == null) return undefined;
    cur = cur[k];
  }
  return cur;
}

function setPath(obj, path, val) {
  const keys = String(path).split('.');
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i += 1) {
    const k = keys[i];
    const next = keys[i + 1];
    if (cur[k] == null) cur[k] = /^\d+$/.test(next) ? [] : {};
    cur = cur[k];
  }
  cur[keys[keys.length - 1]] = val;
}

function draftValue(id, path, fallback) {
  const d = state.drafts[id];
  if (d) {
    const v = getPath(d, path);
    if (v !== undefined) return v;
  }
  return fallback;
}

function collectDraft(id) {
  const out = Object.assign({ id }, state.drafts[id] || {});
  const host = document.getElementById(CARD_ID);
  if (!host) return out;
  host.querySelectorAll('[data-k]').forEach((el) => {
    let v = el.value;
    if (el.type === 'number') {
      if (v === '') return;
      v = Number(v);
    }
    setPath(out, el.getAttribute('data-k'), v);
  });
  return out;
}

function shotTakes(id) {
  return ((state.data.takes || {})[id]) || [];
}

function annotationOf(id) {
  const raw = ((state.data.canvas || {}).annotations || {})[id];
  if (raw && typeof raw === 'object') return raw;
  return { status: 'ok', text: typeof raw === 'string' ? raw : '' };
}

function setAnnotation(id, patch) {
  const canvas = state.data.canvas || (state.data.canvas = {});
  canvas.annotations = canvas.annotations || {};
  canvas.annotations[id] = Object.assign({}, annotationOf(id), patch);
  syncIssueDots();
  saveLayout();
}

function ensureIssueDots() {
  if (state.issueDots || !state.map) return;
  const { THREE } = state.map;
  const geo = new THREE.SphereGeometry(0.09, 8, 8);
  const mat = new THREE.MeshBasicMaterial({ color: 0xff6b6b });
  state.issueDots = new Map();
  state.nodes.forEach((n) => {
    if (!n.mesh) return;
    const dot = new THREE.Mesh(geo, mat);
    dot.position.set(0.34, 0.26, 0);
    dot.visible = false;
    n.mesh.add(dot);
    state.issueDots.set(n.id, dot);
  });
}

function syncIssueDots() {
  if (!state.issueDots) ensureIssueDots();
  if (!state.issueDots) return;
  const ann = (state.data.canvas || {}).annotations || {};
  state.issueDots.forEach((dot, id) => {
    const rec = ann[id];
    dot.visible = !!(rec && typeof rec === 'object' && rec.status === 'issue');
  });
}

const CARD_TABS = [['content', '内容'], ['prompt', '提示词'], ['assets', '资产'],
  ['takes', '版本'], ['qc', 'QC']];

function renderCard(id, tab) {
  const host = document.getElementById(CARD_ID);
  if (!host) return;
  state.currentShot = id;
  state.cardTab = tab || state.cardTab || 'content';
  const shot = (state.data.shots || []).find((s) => s.id === id) || {};
  const qc = (state.data.status && state.data.status[id]) || '未检';
  const tabs = CARD_TABS.map(([k, label]) =>
    '<button type="button" class="sb-tab' + (state.cardTab === k ? ' on' : '') +
    '" data-tab="' + k + '">' + label + '</button>').join('');

  let body = '';
  if (state.cardTab === 'content') {
    const cast = Object.entries(shot.cast || {}).map(([k, v]) => k + '=' + v).join(' · ') || '—';
    const dlg = (shot.dialogue || [])[0];
    const mode = draftValue(id, 'mode', shot.mode || 'i2va');
    const dur = draftValue(id, 'duration', shot.duration != null ? shot.duration : '');
    const img = draftValue(id, 'image', shot.image || '');
    const last = draftValue(id, 'last_image', shot.last_image || '');
    const line = draftValue(id, 'content.shot_line', (shot.content || {}).shot_line || '');
    const dlgText = dlg ? draftValue(id, 'dialogue.0.text', dlg.text || '') : '';
    body =
      '<label class="sb-field"><span>mode</span><select data-k="mode">' +
        ['i2va', 'fl2va', 'ref2va', 'multiref'].map((m) =>
          '<option' + (mode === m ? ' selected' : '') + '>' + m + '</option>').join('') +
      '</select></label>' +
      '<label class="sb-field"><span>时长</span><input data-k="duration" type="number" step="0.001" value="' +
        esc(dur) + '"></label>' +
      '<label class="sb-field"><span>首帧</span><input data-k="image" value="' + esc(img) + '"></label>' +
      '<label class="sb-field"><span>末帧</span><input data-k="last_image" value="' + esc(last) + '"></label>' +
      '<div class="sb-row"><span>cast</span><code>' + esc(cast) + '</code></div>' +
      '<div class="sb-row"><span>场景</span><code>' + esc(shot.scene || '—') + '</code></div>' +
      '<div class="sb-row"><span>QC</span><code>' + esc(qc) + '</code></div>' +
      '<div class="sb-label">动作</div>' +
      '<textarea class="sb-edit" data-k="content.shot_line" rows="6">' + esc(line) + '</textarea>' +
      (dlg ? '<div class="sb-label">台词（' + esc(dlg.speaker || '') + '）</div>' +
        '<textarea class="sb-edit" data-k="dialogue.0.text" rows="3">' + esc(dlgText) + '</textarea>' : '') +
      (shot.soundscape ? '<div class="sb-label">声音</div><pre class="sb-prompt">' + esc(shot.soundscape) + '</pre>' : '');
  } else if (state.cardTab === 'prompt') {
    body = '<pre class="sb-prompt">' + esc((state.data.prompts || {})[id] || '（尚未建稿）') + '</pre>';
  } else if (state.cardTab === 'assets') {
    const assets = (state.data.assets || []).slice(0, 120);
    body = assets.length
      ? '<div class="sb-assets">' + assets.map((a) =>
          '<img data-asset="' + esc(a.path) + '" src="' + esc(assetUrl(a.path)) +
          '" title="' + esc(a.name + '（点=首帧，Shift+点=末帧）') + '">').join('') + '</div>'
      : '<div class="muted small">项目没有可用图片资产</div>';
  } else if (state.cardTab === 'takes') {
    const takes = shotTakes(id);
    const selected = getPath(state.data.canvas || {}, 'nodes.' + id + '.selected_take');
    body = takes.length
      ? takes.slice(0, 8).map((t, i) => {
          const media = t.poster
            ? '<img src="' + esc(assetUrl(t.poster)) + '" loading="lazy">'
            : '<video src="' + esc(assetUrl(t.path)) + '" muted preload="metadata"></video>';
          return '<div class="sb-take' + (selected === t.id ? ' selected' : '') + '">' +
            '<div class="sb-take-media">' + media + '</div>' +
            '<div class="sb-take-meta"><span class="small muted">' +
            esc((t.path || '').split(/[\\/]/).pop()) + '</span>' +
            '<span class="sb-take-actions">' +
            '<button type="button" data-ab="' + i + '">A/B</button>' +
            '<button type="button" data-pick="' + i + '">' + (selected === t.id ? '已选用' : '选用') + '</button>' +
            '</span></div></div>';
        }).join('')
      : '<div class="muted small">还没有 take。单镜出片后这里会出现。</div>';
  } else {
    body =
      '<div class="sb-row"><span>八腿</span><code>' + esc(qc) + '</code></div>' +
      '<div class="small muted">逐腿明细与异常码在 8777 工作台。</div>' +
      '<div class="sb-actions"><a class="btn" target="_blank" rel="noreferrer" href="/?sid=' +
        encodeURIComponent(id) + '">打开工作台</a></div>';
  }

  const ann = annotationOf(id);
  host.innerHTML =
    '<div class="sb-head"><b>' + esc(id) + '</b>' +
      '<button id="sb-close" type="button" title="关闭">×</button></div>' +
    '<div class="sb-tabs">' + tabs + '</div>' +
    '<div class="sb-body">' + body + '</div>' +
    '<div class="sb-anno">' +
      '<textarea id="sb-note" maxlength="100" placeholder="批注（100 字）">' + esc(ann.text || '') + '</textarea>' +
      '<div class="sb-flags">' +
        '<button type="button" data-flag="ok"' + (ann.status === 'ok' ? ' class="on"' : '') + '>标 OK</button>' +
        '<button type="button" data-flag="issue"' + (ann.status === 'issue' ? ' class="on"' : '') + '>标问题</button>' +
      '</div>' +
      CARD_NOTE +
    '</div>' +
    '<div class="sb-actions"><button id="sb-apply" type="button">应用到项目</button></div>';
  host.classList.add('on');
  bindClose();
  bindCard(id);
}

function bindCard(id) {
  const host = document.getElementById(CARD_ID);
  if (!host) return;
  host.querySelectorAll('[data-tab]').forEach((b) => {
    b.onclick = () => renderCard(id, b.getAttribute('data-tab'));
  });
  host.querySelectorAll('[data-asset]').forEach((img) => {
    img.onclick = (e) => {
      const key = e.shiftKey ? 'last_image' : 'image';
      const draft = state.drafts[id] || (state.drafts[id] = { id });
      draft[key] = img.getAttribute('data-asset');
      state.dirty.add(id);
      showHint('已选' + (e.shiftKey ? '末帧' : '首帧') + '：' + img.title.split('（')[0] +
        ' · 点“应用到项目”写入', false, 2400);
    };
  });
  const ta = host.querySelector('#sb-note');
  if (ta) ta.onchange = () => setAnnotation(id, { text: ta.value });
  host.querySelectorAll('[data-flag]').forEach((b) => {
    b.onclick = () => {
      setAnnotation(id, { status: b.getAttribute('data-flag'), text: ta ? ta.value : '' });
      renderCard(id, 'content');
    };
  });
  host.querySelectorAll('[data-k]').forEach((el) => {
    el.onchange = () => {
      state.drafts[id] = collectDraft(id);
      state.dirty.add(id);
      showHint('已修改 ' + id + ' · 点“应用到项目”写回', false, 1600);
    };
  });
  const apply = host.querySelector('#sb-apply');
  if (apply) apply.onclick = () => applyDraft(id);
  host.querySelectorAll('[data-ab]').forEach((b) => {
    b.onclick = () => openAB(id, Number(b.getAttribute('data-ab')));
  });
  host.querySelectorAll('[data-pick]').forEach((b) => {
    b.onclick = () => {
      const takes = shotTakes(id);
      const t = takes[Number(b.getAttribute('data-pick'))];
      if (!t) return;
      state.data.canvas = state.data.canvas || {};
      state.data.canvas.nodes = state.data.canvas.nodes || {};
      state.data.canvas.nodes[id] = state.data.canvas.nodes[id] || {};
      state.data.canvas.nodes[id].selected_take = t.id;
      saveLayout();
      renderCard(id, 'takes');
      showHint('已选用 ' + id + ' 的 ' + (t.path || '').split(/[\\/]/).pop(), false, 2200);
    };
  });
}

function openAB(id, index) {
  const takes = shotTakes(id);
  const a = takes[index];
  const b = takes[index === 0 ? 1 : 0];
  if (!a || !b) {
    showHint('至少需要两条 take 才能 A/B', true, 2200);
    return;
  }
  const win = window.open('', '_blank', 'width=1040,height=640');
  if (!win) {
    showHint('A/B 窗口被浏览器拦截，允许弹窗后重试', true, 2600);
    return;
  }
  const label = (t) => esc((t.path || '').split(/[\\/]/).pop());
  win.document.write(
    '<!doctype html><meta charset="utf-8"><title>' + esc(id) + ' A/B</title>' +
    '<style>body{margin:0;background:#03060c;color:#d7e6f0;font:12px system-ui}' +
    '.row{display:flex;gap:12px;padding:12px}figure{flex:1;margin:0}video{width:100%;background:#000}' +
    'figcaption{padding:6px 2px;color:#8fa6b6;word-break:break-all}</style>' +
    '<div class="row"><figure><video id="a" src="' + esc(assetUrl(a.path)) + '" controls></video>' +
    '<figcaption>A · ' + label(a) + '</figcaption></figure>' +
    '<figure><video id="b" src="' + esc(assetUrl(b.path)) + '" controls></video>' +
    '<figcaption>B · ' + label(b) + '</figcaption></figure></div>');
  win.document.close();
  const va = win.document.getElementById('a');
  const vb = win.document.getElementById('b');
  if (!va || !vb) return;
  let lock = false;
  const sync = (src, dst) => {
    src.addEventListener('play', () => { if (!lock) { lock = true; dst.currentTime = src.currentTime; dst.play().catch(() => {}); lock = false; } });
    src.addEventListener('pause', () => { if (!lock) { lock = true; dst.pause(); lock = false; } });
    src.addEventListener('seeked', () => { if (!lock) { lock = true; dst.currentTime = src.currentTime; lock = false; } });
  };
  sync(va, vb);
  sync(vb, va);
}

async function postApply(drafts, dryRun, perShot) {
  const shots = Array.isArray(drafts) ? drafts : [drafts];
  const res = await fetch('/api/canvas/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project: state.data.project,
      shots,
      dry_run: !!dryRun,
      per_shot: !!perShot,
      edges: state.data.edges || [],
      anchors: Object.fromEntries((state.data.anchors || []).map((a) => [a.label, a.label]))
    })
  });
  return { ok: res.ok, out: await res.json() };
}

function applyErrorText(out) {
  if (!out) return '未知错误';
  if (out.error) return out.error;
  if (Array.isArray(out.results)) {
    return out.results.filter((r) => !r.ok).map((r) =>
      (r.id || '?') + ': ' + (r.error || r.build || r.gate || '失败')).join('\n') || '批量失败';
  }
  if (Array.isArray(out.build)) {
    return out.build.filter((r) => !r.ok).map((r) =>
      (r.id || '?') + ': ' + (r.errors || []).join(' / ')).join('\n') || '建稿失败';
  }
  if (out.gate) return JSON.stringify(out.gate.reasons || out.gate.error || out.gate, null, 1);
  return JSON.stringify(out, null, 1).slice(0, 1500);
}

async function applyDraft(id) {
  if (state.applying) return;
  state.applying = true;
  const btn = document.getElementById('sb-apply');
  if (btn) { btn.disabled = true; btn.textContent = '校验中…'; }
  try {
    state.drafts[id] = collectDraft(id);
    const dry = await postApply(state.drafts[id], true);
    if (!dry.ok || !dry.out.ok) {
      alert('校验未通过：\n' + applyErrorText(dry.out));
      return;
    }
    const diff = (dry.out.diff || []).slice(0, 60).join('\n');
    if (!window.confirm('将要修改 shots.yaml：\n\n' + (diff || '（没有字段变化）') + '\n\n继续？')) return;
    if (btn) btn.textContent = '写回中…';
    const res = await postApply(state.drafts[id], false);
    if (!res.ok || !res.out.ok) {
      alert('已写入但后续失败：\n' + applyErrorText(res.out));
      await refreshState();
      return;
    }
    delete state.drafts[id];
    state.dirty.delete(id);
    await refreshState();
    renderCard(id, 'content');
    showHint('已应用 ' + id + ' · 建稿与闸门已重跑', false, 2600);
  } catch (err) {
    console.error('[fanxing] apply failed', err);
    alert('应用失败：' + (err.message || err));
  } finally {
    state.applying = false;
    if (btn) { btn.disabled = false; btn.textContent = '应用到项目'; }
  }
}

async function refreshState() {
  try {
    const res = await fetch('/api/canvas?project=' + encodeURIComponent(state.data.project),
      { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    state.data = await res.json();
    applyStatusVisuals();
  } catch (err) {
    console.error('[fanxing] refresh state failed', err);
    notifyCard('刷新状态失败：' + (err.message || err));
  }
}

function applyStatusVisuals() {
  const st = state.data.status || {};
  state.nodes.forEach((n, id) => {
    if (!n.shot) return;
    const qc = st[id] || '未检';
    n.sub = qc;
    const color = qc === 'PASS' ? 0x3ddc97 : (qc === 'BLOCK' ? 0xff6b6b : 0x7f909f);
    n.color = color;
    n.status = qc === 'PASS' ? 'pass' : (qc === 'BLOCK' ? 'block' : 'muted');
    if (n.mesh && n.mesh.material && n.mesh.material.uniforms) {
      const u = n.mesh.material.uniforms.uColor;
      if (u && u.value && u.value.setHex) u.value.setHex(color);
    }
    if (n.labelObj && n.labelObj.element) {
      const sub = n.labelObj.element.querySelector('.sub');
      if (sub) sub.textContent = qc;
      const dot = n.labelObj.element.querySelector('.dot');
      if (dot) dot.style.background = '#' + color.toString(16).padStart(6, '0');
    }
  });
}

function renderAnchorCard(target) {
  const host = document.getElementById(CARD_ID);
  if (!host) return;
  const anchor = target.anchor || {};
  host.innerHTML =
    '<div class="sb-head"><b>' + esc(target.id) + '</b>' +
      '<button id="sb-close" type="button" title="关闭">×</button></div>' +
    '<div class="sb-body">' +
      '<div class="sb-row"><span>类型</span><code>' + esc(anchor.kind || '—') + '</code></div>' +
      CARD_NOTE +
    '</div>';
  host.classList.add('on');
  bindClose();
}

// 多选时给一张只读汇总卡：不抢单节点的详情卡，但能看见选中了谁。
function renderSelectionCard(ids) {
  const host = document.getElementById(CARD_ID);
  if (!host) return;
  const shots = [], anchors = [];
  ids.forEach((id) => {
    const n = state.nodes.get(id);
    if (!n) return;
    if (n.kind === 'anchor') anchors.push(id);
    else shots.push(id);
  });
  host.innerHTML =
    '<div class="sb-head"><b>已选 ' + ids.length + '</b>' +
      '<button id="sb-close" type="button" title="关闭">×</button></div>' +
    '<div class="sb-body">' +
      '<div class="sb-row"><span>镜头</span><code>' + esc(shots.join(' ') || '—') + '</code></div>' +
      '<div class="sb-row"><span>锚点</span><code>' + esc(anchors.join(' ') || '—') + '</code></div>' +
      CARD_NOTE +
    '</div>';
  host.classList.add('on');
  bindClose();
}

// 框选/多选后让卡片跟上选中集合：0 关、1 详情、多张汇总。
function syncCardToSelection() {
  const ids = [...state.selected];
  if (!ids.length) { closeCard(); return; }
  if (ids.length === 1) {
    const n = state.nodes.get(ids[0]);
    if (!n) { closeCard(); return; }
    if (n.kind === 'anchor') renderAnchorCard(n);
    else renderCard(ids[0]);
    return;
  }
  renderSelectionCard(ids);
}

// 保存失败之类的提示写进卡片底部：不挡操作，也不抢占卡片主体。
function notifyCard(msg) {
  const host = document.getElementById(CARD_ID);
  if (!host || !host.classList.contains('on')) return;
  let note = host.querySelector('.sb-note.bad');
  if (!note) {
    note = document.createElement('div');
    note.className = 'sb-note bad';
    host.appendChild(note);
  }
  note.textContent = msg;
}

function showErrorCard(title, detail, project) {
  const host = document.getElementById(CARD_ID);
  if (!host) return;
  host.textContent = '';
  const head = document.createElement('div');
  head.className = 'sb-head';
  const b = document.createElement('b');
  b.textContent = title;
  head.appendChild(b);
  host.appendChild(head);
  const body = document.createElement('div');
  body.className = 'sb-body';
  const pre = document.createElement('pre');
  pre.className = 'sb-prompt';
  pre.textContent = [detail, project ? '项目：' + project : ''].filter(Boolean).join('\n');
  body.appendChild(pre);
  host.appendChild(body);
  host.classList.add('on');
}

/* ---------------- 对上层（Task 11/12） ---------------- */

export function selectShot(id) {
  const n = state.nodes.get(id);
  if (!n) return;
  state.map.select(n);
}

// Task 11 拖动每帧调这个：只改内存里的坐标，几何在下一帧统一重算。
// pos 传数组或 Vector3 都行；非法坐标直接忽略，免得把节点甩到 NaN。
export function moveNode(id, pos) {
  const n = state.nodes.get(id);
  if (!n || !n.pos) return false;
  const v = Array.isArray(pos) ? pos : [pos && pos.x, pos && pos.y, pos && pos.z];
  if (!validPos(v)) return false;
  n.pos.fromArray(v);
  if (n.mesh) n.mesh.position.copy(n.pos);
  if (n.labelObj) n.labelObj.position.set(n.pos.x, n.pos.y + LABEL_LIFT, n.pos.z);
  // 记录字段（pinned / note / selected_take）沿用原对象，只覆盖 pos。
  if (state.data) setSavedPos(ensureCanvasNodes(), id, [n.pos.x, n.pos.y, n.pos.z]);
  markEdgeDirty();
  return true;
}

// 挂到 window 上给 Task 11（拖动）和 Task 12（保存）用，不必再 import。
const storyboardApi = { moveNode, markEdgeDirty, selectShot, state, saveLayout };

/* ======================================================================
 * 编辑层（Task 11）：拖动、框选、Shift 多选、出线口连线、撤销/重做、持久化
 * ==================================================================== */

const undo = new CommandStack(50);

const EDGE_SEQ = ['order', 'chain', 'ref'];
// 方向语义：order/chain 起点是上游；ref 起点是引用方（消费方），落点是参考源。
const TYPE_HINT = {
  order: 'order：起点 = 上游 · 落点 = 下游',
  chain: 'chain：起点 = 上游 · 落点 = 下游（需绑定末帧）',
  ref: 'ref：起点 = 引用方 consumer · 落点 = 参考源 source'
};

let hintTimer = null;
let saveChain = Promise.resolve();
let edgeSerial = 0;

function newEdgeId() {
  edgeSerial += 1;
  return 'e' + Date.now().toString(36) + '-' + edgeSerial;
}

// Task 13 会往卡片里加输入框；在那之前就挡住，免得在输入框里按 1/2/3 改线型。
function isTypingTarget(el) {
  if (!el || el.nodeType !== 1) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  return !!el.isContentEditable;
}

/* ---------------- 提示条 / 框选框 ---------------- */

function ensureEditingDom() {
  if (state.overlay) return state.overlay;
  let marquee = document.getElementById('sb-marquee');
  if (!marquee) {
    marquee = document.createElement('div');
    marquee.id = 'sb-marquee';
    document.body.appendChild(marquee);
  }
  let hint = document.getElementById('sb-hint');
  if (!hint) {
    hint = document.createElement('div');
    hint.id = 'sb-hint';
    document.body.appendChild(hint);
  }
  state.overlay = { marquee, hint };
  return state.overlay;
}

function removeEditingDom() {
  clearTimeout(hintTimer);
  hintTimer = null;
  if (!state.overlay) return;
  [state.overlay.marquee, state.overlay.hint].forEach((el) => {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  });
  state.overlay = null;
}

// ms <= 0 表示常驻（拉线过程中用），否则到点自动收。
function showHint(text, bad, ms) {
  const el = state.overlay && state.overlay.hint;
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('bad', !!bad);
  el.style.display = text ? 'block' : 'none';
  clearTimeout(hintTimer);
  hintTimer = null;
  if (text && ms > 0) hintTimer = setTimeout(() => { el.style.display = 'none'; }, ms);
}

/* ---------------- 持久化 ---------------- */

function layoutBody() {
  if (!state.data) return null;
  const canvas = state.data.canvas || {};
  return {
    project: state.data.project || (state.map && state.map.project) || '',
    nodes: canvas.nodes || {},
    edges: state.data.edges || [],
    annotations: canvas.annotations || {}
  };
}

async function postLayout(body) {
  try {
    const res = await fetch('/api/canvas/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json().catch(() => null);
    if (!data || data.ok !== true) throw new Error((data && data.error) || '保存未确认');
    return true;
  } catch (err) {
    // 不能静默：控制台 + 卡片里各留一条，用户还能继续操作。
    console.error('[fanxing] 布局保存失败', err);
    const msg = '布局保存失败：' + ((err && err.message) || err);
    showHint(msg, true, 6000);
    notifyCard(msg);
    return false;
  }
}

// 每次成功编辑（含撤销/重做）都落一次盘；串行排队，避免后发先至把新布局盖回旧的。
function saveLayout() {
  const body = layoutBody();
  if (!body) return saveChain;
  if (!body.project) {
    console.error('[fanxing] 布局未保存：缺少 project');
    notifyCard('布局未保存：缺少项目路径');
    return saveChain;
  }
  saveChain = saveChain.then(() => postLayout(body));
  return saveChain;
}

/* ---------------- 出线口 ---------------- */

function portTexture(THREE) {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.beginPath();
  g.arc(32, 32, 18, 0, Math.PI * 2);
  g.fillStyle = 'rgba(255,255,255,.22)';
  g.fill();
  g.lineWidth = 6;
  g.strokeStyle = 'rgba(255,255,255,.95)';
  g.stroke();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function disposePorts() {
  state.ports.forEach((sprite) => {
    if (state.group) state.group.remove(sprite);
    if (sprite.material) sprite.material.dispose();
  });
  state.ports.clear();
  if (state.portTexture) {
    state.portTexture.dispose();
    state.portTexture = null;
  }
}

// 只有镜头有出线口：锚点只能当落点（数据模型里 ref 的 from 必须是镜头）。
function buildPorts(THREE) {
  disposePorts();
  state.portTexture = portTexture(THREE);
  const color = (EDGE_STYLE[state.currentType] || EDGE_STYLE.order).color;
  state.nodes.forEach((n, id) => {
    if (n.kind !== 'node' || !state.group) return;
    const mat = new THREE.SpriteMaterial({
      map: state.portTexture, color, transparent: true, opacity: 0.95,
      depthWrite: false, depthTest: false
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.setScalar(0.34);
    sprite.renderOrder = 8;
    sprite.userData.port = id;
    state.group.add(sprite);
    state.ports.set(id, sprite);
  });
}

/* ---------------- 边的命令（redo 执行编辑，undo 还原） ---------------- */

function applyEdgeRecord(edge, snapshot) {
  edge.type = snapshot.type;
  if (Object.hasOwn(snapshot, 'binding')) edge.binding = snapshot.binding;
  else delete edge.binding;
  buildEdges();
}

function createEdgeCommand(edge) {
  return {
    redo: () => {
      if (!Array.isArray(state.data.edges)) state.data.edges = [];
      if (!state.data.edges.includes(edge)) state.data.edges.push(edge);
      buildEdges();
    },
    undo: () => {
      state.data.edges = (state.data.edges || []).filter((x) => x !== edge);
      buildEdges();
    }
  };
}

function deleteEdgeCommand(edge) {
  const index = (state.data.edges || []).indexOf(edge);
  return {
    redo: () => {
      state.data.edges = (state.data.edges || []).filter((x) => x !== edge);
      buildEdges();
    },
    undo: () => {
      if (!Array.isArray(state.data.edges)) state.data.edges = [];
      if (!state.data.edges.includes(edge)) {
        const at = Math.max(0, Math.min(index < 0 ? state.data.edges.length : index,
          state.data.edges.length));
        state.data.edges.splice(at, 0, edge);
      }
      buildEdges();
    }
  };
}

/* ---------------- 绑定 ---------------- */

export function bindEditing() {
  const map = state.map;
  if (!map || !state.ready) return false;
  // 同一个 map 只绑一轮；重初始化先 unbindEditing 再进来。
  if (state.editingBound) return true;

  const canvas = map.renderer.domElement;
  const { THREE } = map;
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const hitPoint = new THREE.Vector3();
  const ndc = new THREE.Vector2();
  const camRight = new THREE.Vector3();
  const camUp = new THREE.Vector3();
  const ac = new AbortController();
  const opts = { capture: true, signal: ac.signal };

  state.abort = ac;
  ensureEditingDom();
  buildPorts(THREE);
  map.onFrame(updatePorts);
  state.editingBound = true;
  refreshTypeVisuals();

  /* ---- 拾取 ---- */

  function setRay(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    ndc.x = ((clientX - r.left) / r.width) * 2 - 1;
    ndc.y = -((clientY - r.top) / r.height) * 2 + 1;
    map.raycaster.setFromCamera(ndc, map.camera);
  }

  function nodeAt(clientX, clientY) {
    const pick = map.pickAt(clientX, clientY);
    if (!pick || (pick.kind !== 'node' && pick.kind !== 'anchor')) return null;
    return state.nodes.get(pick.id) || null;
  }

  // 出线口是 Sprite；命中优先于节点本体，避免点端口变成拖节点。
  function pickPort(e) {
    if (!state.ports.size) return null;
    setRay(e.clientX, e.clientY);
    const hits = map.raycaster.intersectObjects([...state.ports.values()], false);
    if (!hits.length) return null;
    const id = hits[0].object.userData.port;
    return state.nodes.has(id) ? id : null;
  }

  function edgeAt(e) {
    if (!state.edgeObjs.length) return null;
    setRay(e.clientX, e.clientY);
    const ray = map.raycaster;
    const prev = ray.params.Line.threshold;
    ray.params.Line.threshold = 0.35;
    try {
      const hits = ray.intersectObjects(state.edgeObjs.map((o) => o.line), false);
      return hits.length ? (hits[0].object.userData.edge || null) : null;
    } finally {
      // 阈值是 raycaster 的全局参数，用完还原，别影响别的拾取。
      ray.params.Line.threshold = prev;
    }
  }

  // 出线口贴在节点右下方：每帧按相机右/上方向重新摆，和 billboard 圆盘同步。
  function updatePorts() {
    const m = map.camera.matrixWorld.elements;
    camRight.set(m[0], m[1], m[2]).normalize();
    camUp.set(m[4], m[5], m[6]).normalize();
    state.ports.forEach((sprite, id) => {
      const n = state.nodes.get(id);
      if (!n) return;
      sprite.position.copy(n.pos)
        .addScaledVector(camRight, 0.52)
        .addScaledVector(camUp, -0.34);
    });
  }

  function refreshTypeVisuals() {
    const style = EDGE_STYLE[state.currentType] || EDGE_STYLE.order;
    state.ports.forEach((sprite) => {
      if (sprite.material) sprite.material.color.setHex(style.color);
    });
    if (state.preview && state.preview.material) state.preview.material.color.setHex(style.color);
    // 悬停画布时的原生 tooltip 也能看到方向语义。
    canvas.title = '新线型 · ' + TYPE_HINT[state.currentType];
  }

  /* ---- 拖线预览 ---- */

  function beginPreview(n) {
    removePreview();
    const style = EDGE_STYLE[state.currentType] || EDGE_STYLE.order;
    const mat = new THREE.LineBasicMaterial({
      color: style.color, transparent: true, opacity: 0.9, depthWrite: false
    });
    const geo = new THREE.BufferGeometry().setFromPoints([n.pos.clone(), n.pos.clone()]);
    const line = new THREE.Line(geo, mat);
    state.group.add(line);
    state.preview = line;
  }

  function updatePreview(e) {
    const conn = state.connecting;
    if (!conn || !state.preview) return;
    const n = state.nodes.get(conn.from);
    if (!n) return;
    plane.constant = -n.pos.y;
    setRay(e.clientX, e.clientY);
    const end = map.raycaster.ray.intersectPlane(plane, hitPoint)
      ? hitPoint.clone()
      : n.pos.clone().addScaledVector(camRight, 1.5);
    state.preview.geometry.setFromPoints([n.pos.clone(), end]);
  }

  /* ---- 拖动 ---- */

  function dragMove(e) {
    const d = state.dragging;
    if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.px, e.clientY - d.py) < 3) return;
    d.moved = true;
    const n = state.nodes.get(d.id);
    if (!n) return;
    // 水平面锁在被拖节点的 y 上；x/z 吸附 0.5。
    plane.constant = -d.start.y;
    setRay(e.clientX, e.clientY);
    if (!map.raycaster.ray.intersectPlane(plane, hitPoint)) return;
    moveNode(d.id, [snap(hitPoint.x), d.start.y, snap(hitPoint.z)]);
  }

  function finishDrag(e) {
    const d = state.dragging;
    state.dragging = null;
    map.controls.enabled = true;
    if (!d) return;
    const n = state.nodes.get(d.id);
    if (!n) return;
    const after = [n.pos.x, n.pos.y, n.pos.z];
    const before = d.start.toArray();
    const dist = Math.hypot(after[0] - before[0], after[2] - before[2]);
    if (dist > 1e-9) {
      // CommandStack.push 会先跑一次 redo（坐标已在拖动中到位，幂等）。
      undo.push({
        redo: () => moveNode(d.id, after),
        undo: () => moveNode(d.id, before)
      });
      saveLayout();
      showHint('已移动 ' + d.id + '（吸附 0.5）· Ctrl+Z 撤销', false, 2200);
    } else if (!d.moved && n) {
      // 没拖动 = 单击：走 map3d 的 select，onSelect 会点亮并开卡片。
      map.select(n);
    }
    markEdgeDirty();
  }

  /* ---- 框选 ---- */

  function marqueeBox(m) {
    const x = Math.min(m.x0, m.x1);
    const y = Math.min(m.y0, m.y1);
    const el = state.overlay && state.overlay.marquee;
    if (!el) return;
    el.style.left = x + 'px';
    el.style.top = y + 'px';
    el.style.width = Math.abs(m.x1 - m.x0) + 'px';
    el.style.height = Math.abs(m.y1 - m.y0) + 'px';
  }

  function startMarquee(e) {
    state.marquee = { x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY };
    map.controls.enabled = false;
    const el = state.overlay && state.overlay.marquee;
    if (el) {
      el.style.display = 'block';
      marqueeBox(state.marquee);
    }
  }

  function finishMarquee() {
    const m = state.marquee;
    state.marquee = null;
    map.controls.enabled = true;
    if (state.overlay) state.overlay.marquee.style.display = 'none';
    if (!m) return;
    const rect = {
      x: Math.min(m.x0, m.x1), y: Math.min(m.y0, m.y1),
      w: Math.abs(m.x1 - m.x0), h: Math.abs(m.y1 - m.y0)
    };
    if (rect.w < 2 && rect.h < 2) {
      // Shift+点空白：清空选中，和常见画布一致。
      setSelection([]);
      closeCard();
      return;
    }
    const cr = canvas.getBoundingClientRect();
    map.camera.updateMatrixWorld();
    const pts = [];
    state.nodes.forEach((n, id) => {
      const p = n.pos.clone().project(map.camera);
      pts.push({
        id,
        x: cr.left + (p.x + 1) / 2 * cr.width,
        y: cr.top + (1 - p.y) / 2 * cr.height
      });
    });
    const ids = screenRectSelect(pts, rect);
    setSelection(ids);
    syncCardToSelection();
    showHint(ids.length ? '已框选 ' + ids.length + ' 个节点' : '框选未命中节点', false, 1600);
  }

  /* ---- 连线 ---- */

  function startConnect(id, e) {
    e.preventDefault();
    e.stopPropagation();
    const n = state.nodes.get(id);
    if (!n) return;
    state.connecting = { from: id };
    map.controls.enabled = false;
    canvas.style.cursor = 'crosshair';
    beginPreview(n);
    showHint('拉线中 · ' + TYPE_HINT[state.currentType] + ' · 1/2/3 换线型', false, 0);
  }

  function finishConnect(e) {
    const conn = state.connecting;
    // 先把状态收干净：prompt 取消/抛错时控件不能锁死。
    state.connecting = null;
    removePreview();
    map.controls.enabled = true;
    canvas.style.cursor = '';
    if (!conn) return;
    const start = state.nodes.get(conn.from);
    const target = nodeAt(e.clientX, e.clientY);
    if (!start || !target || target.id === conn.from) {
      showHint('未连线：请从镜头出线口拖到另一个镜头/锚点', true, 2200);
      return;
    }
    const type = EDGE_STYLE[state.currentType] ? state.currentType : 'order';
    if ((state.data.edges || []).some(
      (x) => x.from === conn.from && x.to === target.id && x.type === type)) {
      showHint('这条线已经存在：' + conn.from + ' → ' + target.id + '（' + type + '）', true, 2400);
      return;
    }
    let binding;
    if (type === 'chain') {
      const raw = window.prompt('首尾帧链：绑定末帧文件名（例如 U01_end.png）');
      if (raw == null || !String(raw).trim()) {
        // 取消：不建边，但连线状态和控件已在上面恢复。
        showHint('已取消 chain 连线', true, 2200);
        return;
      }
      binding = String(raw).trim();
    }
    const edge = { id: newEdgeId(), from: conn.from, to: target.id, type };
    if (binding) edge.binding = binding;
    undo.push(createEdgeCommand(edge));
    saveLayout();
    const dir = type === 'ref' ? '引用方 → 参考源' : '上游 → 下游';
    showHint('已连线 ' + conn.from + ' → ' + target.id + '（' + type + '，' + dir +
      '）· Ctrl+Z 撤销', false, 2800);
  }

  /* ---- 事件 ---------------- */

  function onPointerDown(e) {
    if (!state.ready || e.button !== 0 || e.isPrimary === false) return;
    if (e.target !== canvas) return;
    if (state.dragging || state.connecting || state.marquee) return;

    const portId = pickPort(e);
    if (portId) { startConnect(portId, e); return; }

    const node = nodeAt(e.clientX, e.clientY);
    if (e.shiftKey) {
      // Shift+拖空白 = 框选（这一路必须拦住 OrbitControls，否则相机跟着转）。
      e.preventDefault();
      e.stopPropagation();
      if (node) {
        toggleSelection(node.id);
        showHint('已选 ' + state.selected.size + ' 个节点', false, 1200);
      } else {
        startMarquee(e);
      }
      return;
    }
    if (!node) return;   // 空白：交给 map3d 的 OrbitControls / 清选中

    // 节点：先接管 pointerdown，拖动期间不让 OrbitControls 拿到手势。
    e.stopPropagation();
    state.dragging = {
      id: node.id, start: node.pos.clone(),
      px: e.clientX, py: e.clientY, moved: false
    };
    map.controls.enabled = false;
  }

  function onPointerMove(e) {
    if (state.dragging) { dragMove(e); return; }
    if (state.marquee) {
      state.marquee.x1 = e.clientX;
      state.marquee.y1 = e.clientY;
      marqueeBox(state.marquee);
      return;
    }
    if (state.connecting) updatePreview(e);
  }

  function onPointerUp(e) {
    if (state.dragging) { finishDrag(e); return; }
    if (state.marquee) { finishMarquee(); return; }
    if (state.connecting) finishConnect(e);
  }

  function onPointerCancel() {
    if (state.dragging) {
      const d = state.dragging;
      state.dragging = null;
      if (d) moveNode(d.id, d.start.toArray());
      map.controls.enabled = true;
      markEdgeDirty();
    }
    if (state.marquee) {
      state.marquee = null;
      if (state.overlay) state.overlay.marquee.style.display = 'none';
      map.controls.enabled = true;
    }
    if (state.connecting) {
      state.connecting = null;
      removePreview();
      map.controls.enabled = true;
      canvas.style.cursor = '';
    }
    showHint('', false, 0);
  }

  function setEdgeType(type) {
    if (!EDGE_SEQ.includes(type)) return;
    state.currentType = type;
    refreshTypeVisuals();
    showHint('新线型 · ' + TYPE_HINT[type] + ' · 1/2/3 切换', false, 2600);
    console.info('[fanxing] 新线型 ' + TYPE_HINT[type]);
  }

  function onKeyDown(e) {
    if (!state.ready) return;
    if (isTypingTarget(e.target) || isTypingTarget(document.activeElement)) return;

    if (e.ctrlKey || e.metaKey) {
      if (e.altKey) return;
      const key = String(e.key || '').toLowerCase();
      if (key !== 'z' && key !== 'y') return;
      if (state.dragging || state.connecting || state.marquee) return;
      e.preventDefault();
      const redo = key === 'y' || e.shiftKey;
      const ok = redo ? undo.redo() : undo.undo();
      if (!ok) return;
      // 撤销/重做也落盘，否则刷新后历史白做。
      markEdgeDirty();
      saveLayout();
      showHint((redo ? '已重做' : '已撤销') + ' · 已保存', false, 1400);
      return;
    }
    if (e.altKey) return;
    const type = edgeTypeForKey(e.key);
    if (!type) return;
    e.preventDefault();
    setEdgeType(type);
  }

  function onDblClick(e) {
    if (!state.ready || e.target !== canvas) return;
    if (state.dragging || state.connecting || state.marquee) return;
    const edge = edgeAt(e);
    if (!edge) return;
    // 拦在 map3d 的 dblclick 之前：删边时不要再顺手聚焦节点。
    e.preventDefault();
    e.stopPropagation();
    undo.push(deleteEdgeCommand(edge));
    saveLayout();
    showHint('已删除连线 ' + edge.from + ' → ' + edge.to + ' · Ctrl+Z 撤销', false, 2600);
  }

  function onContextMenu(e) {
    if (!state.ready || e.target !== canvas) return;
    const edge = edgeAt(e);
    if (!edge) return;
    e.preventDefault();
    e.stopPropagation();
    if (state.dragging || state.connecting || state.marquee) return;
    const cur = EDGE_SEQ.indexOf(edge.type);
    const next = EDGE_SEQ[(cur + 1) % EDGE_SEQ.length];
    let binding;
    if (next === 'chain') {
      const raw = window.prompt('切换为 chain：绑定末帧文件名（例如 U01_end.png）');
      if (raw == null || !String(raw).trim()) {
        // 取消不改类型：prompt 之前一个字段都没动。
        showHint('已取消改线型（保持 ' + edge.type + '）', true, 2000);
        return;
      }
      binding = String(raw).trim();
    }
    const prev = { type: edge.type };
    if (Object.hasOwn(edge, 'binding')) prev.binding = edge.binding;
    const nextState = { type: next };
    if (binding) nextState.binding = binding;
    undo.push({
      redo: () => applyEdgeRecord(edge, nextState),
      undo: () => applyEdgeRecord(edge, prev)
    });
    saveLayout();
    showHint('线型 → ' + next + (binding ? '（binding ' + binding + '）' : ''), false, 2400);
  }

  window.addEventListener('pointerdown', onPointerDown, opts);
  window.addEventListener('pointermove', onPointerMove, opts);
  window.addEventListener('pointerup', onPointerUp, opts);
  window.addEventListener('pointercancel', onPointerCancel, opts);
  window.addEventListener('keydown', onKeyDown, opts);
  window.addEventListener('dblclick', onDblClick, opts);
  window.addEventListener('contextmenu', onContextMenu, opts);
  return true;
}

function unbindEditing() {
  if (state.abort) {
    state.abort.abort();
    state.abort = null;
  }
  state.editingBound = false;
  removePreview();
  removeEditingDom();
  state.dragging = null;
  state.connecting = null;
  state.marquee = null;
  if (state.map && state.map.controls) state.map.controls.enabled = true;
  if (state.map && state.map.renderer) state.map.renderer.domElement.style.cursor = '';
}

// 拆除/取消时按 state.preview 清掉拖线预览（bindEditing 里也复用它）。
function removePreview() {
  if (!state.preview) return;
  if (state.group) state.group.remove(state.preview);
  if (state.preview.geometry) state.preview.geometry.dispose();
  if (state.preview.material) state.preview.material.dispose();
  state.preview = null;
}

/* ---------------- 顶部工具栏：批量应用 / 跑闸 / 出片 / 项目切换 ---------------- */

let toolbarBound = false;
let shotBusy = false;

function setStatus(text, bad) {
  const el = document.getElementById('sb-est');
  if (!el) return;
  el.textContent = text || '';
  el.style.color = bad ? '#ff8b8b' : '';
}

async function initToolbar() {
  if (toolbarBound) return;
  toolbarBound = true;
  bindLiveEvents();
  const sel = document.getElementById('sb-project');
  if (!sel) return;

  async function loadProjects() {
    try {
      const r = await fetch('/api/projects', { cache: 'no-store' });
      const d = await r.json();
      const list = d.projects || [];
      if (!list.some((p) => p.path === state.data.project)) {
        list.unshift({ name: '当前项目', path: state.data.project, shot_count: state.data.shots.length });
      }
      sel.innerHTML = list.map((p) =>
        '<option value="' + esc(p.path) + '">' + esc(p.name) + ' (' + (p.shot_count || 0) + ')</option>'
      ).join('');
      sel.value = state.data.project;
    } catch (err) {
      console.error('[fanxing] projects failed', err);
    }
  }

  function confirmLeave() {
    return !state.dirty.size || window.confirm('有未应用的编辑，切换项目会丢失。继续？');
  }

  sel.onchange = () => {
    if (!confirmLeave()) { sel.value = state.data.project; return; }
    location.href = '/canvas?project=' + encodeURIComponent(sel.value);
  };

  async function shotAction(action) {
    if (shotBusy) return;
    const template = state.currentShot || (state.data.shots[0] || {}).id;
    if (action === 'delete' && !state.currentShot) {
      alert('先选一个镜头');
      return;
    }
    if (action === 'delete' && !window.confirm('删除 ' + state.currentShot + '？会直接写 shots.yaml')) return;
    if (action === 'add' && !template) {
      alert('没有可复制的模板镜头');
      return;
    }
    if (action === 'add' && !window.confirm('复制 ' + template + ' 新增一镜？')) return;
    shotBusy = true;
    const addBtn = document.getElementById('sb-add');
    const delBtn = document.getElementById('sb-del');
    if (addBtn) addBtn.disabled = true;
    if (delBtn) delBtn.disabled = true;
    try {
      const r = await fetch('/api/canvas/shot', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project: state.data.project, action,
          template, id: state.currentShot
        })
      });
      const out = await r.json();
      if (out.error) { alert(out.error); return; }
      location.reload();
    } catch (err) {
      alert('镜头操作失败：' + (err.message || err));
    } finally {
      shotBusy = false;
      if (addBtn) addBtn.disabled = false;
      if (delBtn) delBtn.disabled = false;
    }
  }

  async function batchApply() {
    const ids = [...state.dirty];
    const drafts = ids.map((id) => state.drafts[id]).filter(Boolean);
    if (!drafts.length) { alert('没有改动的镜头'); return; }
    setStatus('校验 ' + drafts.length + ' 镜…');
    const dry = await postApply(drafts, true, true);
    if (!dry.ok || !dry.out.ok) {
      setStatus('校验失败', true);
      alert('校验未通过：\n' + applyErrorText(dry.out));
      return;
    }
    const diff = dry.out.results
      ? dry.out.results.map((r) => '--- ' + r.id + '\n' + ((r.diff || []).join('\n'))).join('\n').slice(0, 5000)
      : (dry.out.diff || []).slice(0, 80).join('\n');
    if (!window.confirm('将修改 ' + drafts.length + ' 镜：\n\n' + diff + '\n\n继续？')) {
      setStatus('');
      return;
    }
    setStatus('写回 ' + drafts.length + ' 镜…');
    const res = await postApply(drafts, false, true);
    if (!res.ok || !res.out.ok) {
      setStatus('批量应用失败', true);
      alert('已部分写入但后续失败：\n' + applyErrorText(res.out));
      await refreshState();
      return;
    }
    state.dirty.clear();
    state.drafts = {};
    await refreshState();
    setStatus('已应用 ' + drafts.length + ' 镜');
    showHint('批量应用完成：' + drafts.length + ' 镜', false, 2600);
  }

  async function batchRun(stage) {
    const shots = (state.data.shots || []).map((s) => s.id);
    if (!shots.length) { alert('项目没有镜头'); return; }
    const est = Math.round(shots.length * 7);
    const extra = stage === 'run' ? '会提交 8189 出片' : '只跑建稿与八腿闸';
    if (!window.confirm('共 ' + shots.length + ' 镜，预计约 ' + est + ' 分钟。' + extra + '。继续？')) return;
    setStatus('提交任务…');
    try {
      const r = await fetch('/api/canvas/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: state.data.project, shots, stage, confirm: true })
      });
      const out = await r.json();
      if (out.error) { setStatus(out.error, true); alert(out.error); return; }
      watchJob(out.job_id);
    } catch (err) {
      setStatus('提交失败', true);
      alert('提交失败：' + (err.message || err));
    }
  }

  function bindLiveEvents() {
    if (liveBound) return;
    liveBound = true;
    window.addEventListener('fanxing:job', (e) => {
      const d = e.detail || {};
      if (d.type === 'status') {
        setStatus(d.status === 'running' ? '出片中'
          : (d.status === 'gating' ? '闸门中' : '任务 ' + d.status));
        if (JOB_TERMINAL.includes(d.status)) {
          refreshState();
          if (d.status === 'done') showHint('任务完成', false, 3000);
          else showHint('任务 ' + d.status, true, 4200);
        }
      } else if (d.type === 'stage' && d.status === 'running') {
        setStatus((d.label || d.stage || '阶段') + '中');
      } else if (d.type === 'shot' && (d.state === 'done' || d.state === 'failed')) {
        setStatus(d.shot + (d.state === 'done' ? ' 出片完成' : ' 出片失败'));
      }
    });
  }

  function watchJob(jobId) {
    setStatus('任务 ' + jobId + ' 已提交');
    bindLiveEvents();
    if (window.__fanxingLive && window.__fanxingLive.watch) {
      window.__fanxingLive.watch(jobId);
      return;
    }
    // 面板缺席时保留旧兜底：SSE + 4 秒轮询。
    let es = null;
    try {
      es = new EventSource('/api/canvas/jobs/' + encodeURIComponent(jobId) + '/events');
      es.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data || '{}');
          if (d.line) setStatus(d.line.slice(0, 120));
        } catch (_) { /* ignore */ }
      };
    } catch (_) { es = null; }
    const timer = setInterval(async () => {
      try {
        const r = await fetch('/api/canvas/jobs/' + encodeURIComponent(jobId), { cache: 'no-store' });
        const j = await r.json();
        if (j.error) return;
        const last = (j.log || []).slice(-1)[0] || '';
        setStatus(j.status + (last ? ' · ' + last.slice(0, 100) : ''));
        if (JOB_TERMINAL.includes(j.status)) {
          clearInterval(timer);
          if (es) es.close();
          await refreshState();
          if (j.status === 'done') showHint('任务完成', false, 3000);
          else showHint('任务 ' + j.status, true, 4200);
        }
      } catch (err) {
        console.error('[fanxing] job poll failed', err);
      }
    }, 4000);
  }

  document.getElementById('sb-add').onclick = () => shotAction('add');
  document.getElementById('sb-del').onclick = () => shotAction('delete');
  document.getElementById('sb-apply-all').onclick = batchApply;
  document.getElementById('sb-gate').onclick = () => batchRun('gate');
  document.getElementById('sb-run').onclick = () => batchRun('run');

  const railBtn = document.getElementById('sb-rail');
  const syncRailBtn = () => {
    if (!railBtn) return;
    const collapsed = document.body.classList.contains('rail-collapsed');
    railBtn.textContent = collapsed ? '展开数据' : '收起数据';
    railBtn.classList.toggle('active', !collapsed);
  };
  if (railBtn) {
    railBtn.onclick = () => {
      if (window.__fanxingLive && window.__fanxingLive.toggle) {
        window.__fanxingLive.toggle();
      } else {
        document.body.classList.toggle('rail-collapsed');
      }
      syncRailBtn();
    };
    window.addEventListener('fanxing:rail', syncRailBtn);
    syncRailBtn();
  }
  await loadProjects();
}
