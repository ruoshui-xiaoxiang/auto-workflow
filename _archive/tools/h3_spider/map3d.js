import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';

THREE.ColorManagement.enabled = false;

// 单一主星图：质检星系 + 可编辑的镜头星系都在这张图里，不再分「画布/质检」两页。
const QS = new URLSearchParams(location.search);
const PROJECT = QS.get('project') || '';

const C = {
  bg: 0x03060c,
  accent: 0x5eead4,
  sky: 0x38bdf8,
  green: 0x3ddc97,
  amber: 0xf5b955,
  red: 0xff6b6b,
  purple: 0xb794f6,
  muted: 0x7f909f,
  line: 0x2f4658
};

const sceneHost = document.getElementById('scene');
const labelsHost = document.getElementById('labels');
const inspector = document.getElementById('inspector');
const loading = document.getElementById('loading');
const fatal = document.getElementById('fatal');
const fatalMsg = document.getElementById('fatal-msg');

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const hash = (n) => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/* ---------------- shaders ---------------- */

const SKY_VS = `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const SKY_FS = `
precision highp float;
varying vec2 vUv;
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uCam;

float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
vec2 hash22(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.xx + p3.yz) * p3.zy);
}
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.52;
  mat2 m = mat2(0.80, 0.60, -0.60, 0.80);
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = m * p * 2.02 + 13.7;
    a *= 0.5;
  }
  return v;
}
float ridge(vec2 p) {
  float v = 0.0;
  float a = 0.55;
  mat2 m = mat2(0.80, 0.60, -0.60, 0.80);
  for (int i = 0; i < 4; i++) {
    float n = 1.0 - abs(noise(p) * 2.0 - 1.0);
    v += a * n * n;
    p = m * p * 2.10 + 7.3;
    a *= 0.5;
  }
  return v;
}
vec3 nebula(vec2 p, float t) {
  vec2 drift = vec2(t * 0.004, -t * 0.003);
  vec2 q = vec2(
    fbm(p * 1.15 + drift),
    fbm(p * 1.15 + vec2(5.2, 1.7) - drift * 0.8)
  );
  vec2 w = p + (q - 0.5) * 1.25;

  float dA = length((p - vec2(-0.62, 0.26)) * vec2(0.90, 1.10));
  float dB = length((p - vec2( 0.64, 0.04)) * vec2(1.10, 0.80));
  float dC = length((p - vec2( 0.02,-0.70)) * vec2(1.35, 1.00));
  float mask = exp(-dA * dA * 2.4) * 1.00
             + exp(-dB * dB * 2.0) * 0.90
             + exp(-dC * dC * 3.2) * 0.30;

  float n1 = fbm(w * 1.35);
  float n2 = fbm(w * 4.6 + vec2(3.7, 1.9));
  float n = n1 * 0.66 + n2 * 0.34;
  float cloud = smoothstep(0.44, 0.78, n * (0.50 + 0.95 * mask));

  float dust = smoothstep(0.49, 0.57, fbm(w * 1.85 + vec2(8.3, 3.1) + drift * 0.6));
  float d = cloud * (1.0 - 0.90 * dust);

  float fil = ridge(w * 4.2 + vec2(1.4, 6.2));
  float vein = smoothstep(0.64, 0.98, fil) * cloud;
  float fil2 = ridge(w * 8.0 + vec2(9.1, 2.4));
  vein += smoothstep(0.78, 1.00, fil2) * cloud * 0.35;

  vec3 col = vec3(0.0);
  col += vec3(0.018, 0.070, 0.090) * pow(d, 1.1) * 1.70;
  col += vec3(0.030, 0.110, 0.270) * pow(d, 2.6) * 2.00;
  col += vec3(0.330, 0.090, 0.240) * vein * 0.60;
  col += vec3(0.480, 0.680, 0.820) * pow(vein, 2.6) * 0.50;
  return col;
}
vec3 starLayer(vec2 p, float scale, float density, float t, float seed, float gain) {
  vec2 sp = p * scale + seed;
  vec2 id = floor(sp);
  vec2 gv = fract(sp) - 0.5;
  float h = hash21(id + seed * 1.31);
  float on = step(density, h);
  vec2 off = (hash22(id + seed * 1.71) - 0.5) * 0.62;
  vec2 d = gv - off;
  float dist = length(d);
  float r = 0.022 + 0.045 * pow(h, 8.0);
  float core = smoothstep(r, 0.0, dist);
  float halo = exp(-dist * dist / (r * r * 9.0)) * 0.16;
  float tw = 0.78 + 0.22 * sin(t * (0.5 + h * 2.0) + h * 61.0);
  float mag = (0.16 + 2.0 * pow(h, 5.0)) * tw * gain;
  vec3 tint = mix(vec3(0.66, 0.80, 1.00), vec3(1.00, 0.87, 0.72), hash21(id + 9.1));
  return tint * (core * 1.35 + halo) * mag * on;
}

void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y * 2.0;
  vec2 base = p + uCam;
  vec3 col = vec3(0.002, 0.005, 0.012);
  col += vec3(0.006, 0.014, 0.030) * fbm(base * 1.5 + 2.3);
  col += nebula(base, uTime) * 0.80;

  float band = exp(-pow(dot(base, normalize(vec2(0.74, 0.67))) * 2.35, 2.0));
  col += vec3(0.040, 0.060, 0.105) * band * fbm(base * 2.2 + 4.0) * 1.7;

  col += starLayer(base, 27.0, 0.9920, uTime, 3.7, 0.85);
  col += starLayer(base, 54.0, 0.9840, uTime, 11.3, 0.50);

  col = 1.0 - exp(-col * 1.55);
  gl_FragColor = vec4(col, 1.0);
}`;

const NODE_VS = `
uniform float uScale;
varying vec2 vUv;
void main() {
  vec4 mv = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  mv.xy += position.xy * uScale;
  gl_Position = projectionMatrix * mv;
  vUv = uv;
}`;

const NODE_FS = `
precision highp float;
uniform vec3 uColor;
uniform float uHover;
uniform float uSelected;
uniform float uWarn;
uniform float uFlash;
uniform vec3 uFlashColor;
uniform float uTime;
varying vec2 vUv;
void main() {
  vec2 p = (vUv - 0.5) * 2.0;
  float r = length(p);
  if (r > 1.0) discard;

  float core = 1.0 - smoothstep(0.0, 0.46, r);
  float ring = smoothstep(0.47, 0.53, r) - smoothstep(0.57, 0.63, r);
  float glow = pow(max(0.0, 1.0 - r), 2.4);
  float selRing = smoothstep(0.80, 0.84, r) - smoothstep(0.88, 0.92, r);
  float warnRing = smoothstep(0.70, 0.725, r) - smoothstep(0.755, 0.78, r);
  float flashGlow = pow(max(0.0, 1.0 - r), 1.7) * uFlash;
  float flashRing = (smoothstep(0.60, 0.64, r) - smoothstep(0.70, 0.74, r)) * uFlash;

  float ang = atan(p.y, p.x);
  warnRing *= step(0.42, fract(ang * 4.77));
  float tick = (smoothstep(0.86, 0.88, r) - smoothstep(0.90, 0.92, r))
             * step(0.72, sin(ang * 6.0 + uTime * 1.7)) * uSelected;

  vec3 col = min(uColor * 1.12, vec3(1.0));
  col = mix(col, vec3(1.0), core * 0.62);
  float a = core * 0.98 + ring * 0.92 + glow * 0.40;
  a += selRing * uSelected + tick * 0.8;
  col = mix(col, vec3(1.0), selRing * uSelected * 0.65);
  a += (ring + core) * uHover * 0.22;
  a += warnRing * uWarn * 0.9;
  col = mix(col, vec3(0.96, 0.72, 0.33), warnRing * uWarn);
  a += flashGlow * 0.85 + flashRing * 0.75;
  col = mix(col, uFlashColor, clamp(flashGlow * 0.9 + flashRing * 0.7, 0.0, 1.0));
  gl_FragColor = vec4(col, clamp(a, 0.0, 1.0));
}`;

const GRADE_SHADER = {
  uniforms: {
    tDiffuse: { value: null },
    uTime: { value: 0 }
  },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform float uTime;
    varying vec2 vUv;
    void main() {
      vec2 uv = vUv;
      vec2 d = uv - 0.5;
      float r2 = dot(d, d);
      vec2 off = d * (0.0014 + 0.0026 * r2);
      vec3 c;
      c.r = texture2D(tDiffuse, uv + off).r;
      c.g = texture2D(tDiffuse, uv).g;
      c.b = texture2D(tDiffuse, uv - off).b;
      c = c * (1.0 + c * 0.16) / (1.0 + c * 0.52);
      c *= vec3(0.97, 1.0, 1.035);
      c *= 1.0 - 0.44 * pow(clamp(length(d) * 1.3, 0.0, 1.0), 2.2);
      float g = fract(sin(dot(uv * vec2(1731.0, 1973.0) + uTime, vec2(12.9898, 78.233))) * 43758.5453);
      c += (g - 0.5) * 0.012;
      gl_FragColor = vec4(c, 1.0);
    }`
};

/* ---------------- textures ---------------- */

function glowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, 'rgba(255,255,255,1)');
  gr.addColorStop(0.18, 'rgba(255,255,255,.92)');
  gr.addColorStop(0.45, 'rgba(255,255,255,.30)');
  gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function starTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  gr.addColorStop(0, 'rgba(255,255,255,1)');
  gr.addColorStop(0.30, 'rgba(255,255,255,.75)');
  gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr;
  g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function flareTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d');
  g.globalCompositeOperation = 'lighter';
  const gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  gr.addColorStop(0, 'rgba(255,255,255,.95)');
  gr.addColorStop(0.08, 'rgba(255,255,255,.55)');
  gr.addColorStop(0.28, 'rgba(255,255,255,.12)');
  gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr;
  g.fillRect(0, 0, 256, 256);

  const h = g.createLinearGradient(0, 128, 256, 128);
  h.addColorStop(0, 'rgba(255,255,255,0)');
  h.addColorStop(0.35, 'rgba(255,255,255,.05)');
  h.addColorStop(0.5, 'rgba(255,255,255,.7)');
  h.addColorStop(0.65, 'rgba(255,255,255,.05)');
  h.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = h;
  g.fillRect(0, 124, 256, 8);

  const v = g.createLinearGradient(128, 0, 128, 256);
  v.addColorStop(0, 'rgba(255,255,255,0)');
  v.addColorStop(0.4, 'rgba(255,255,255,.04)');
  v.addColorStop(0.5, 'rgba(255,255,255,.5)');
  v.addColorStop(0.6, 'rgba(255,255,255,.04)');
  v.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = v;
  g.fillRect(124, 0, 8, 256);

  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function galaxyTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  g.translate(64, 64);
  g.scale(1, 0.34);
  const gr = g.createRadialGradient(0, 0, 0, 0, 0, 62);
  gr.addColorStop(0, 'rgba(255,255,255,.95)');
  gr.addColorStop(0.12, 'rgba(255,255,255,.55)');
  gr.addColorStop(0.42, 'rgba(255,255,255,.14)');
  gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr;
  g.beginPath();
  g.arc(0, 0, 62, 0, Math.PI * 2);
  g.fill();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

const TEX_GLOW = glowTexture();
const TEX_STAR = starTexture();
const TEX_FLARE = flareTexture();
const TEX_GALAXY = galaxyTexture();

/* ---------------- data ---------------- */

async function loadData() {
  const res = await fetch('/api/batch', { cache: 'no-store' });
  if (!res.ok) throw new Error('批次接口 HTTP ' + res.status);
  return res.json();
}

async function loadWorkflow() {
  try {
    const res = await fetch('/api/workflow', { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    return null;
  }
}

async function loadKb() {
  try {
    const res = await fetch('/api/kb', { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    return null;
  }
}

async function loadCanvas(project) {
  const res = await fetch('/api/canvas?project=' + encodeURIComponent(project), { cache: 'no-store' });
  if (!res.ok) throw new Error('画布接口 HTTP ' + res.status);
  return res.json();
}

async function resolveCanvasProject() {
  if (PROJECT) return PROJECT;
  try {
    const res = await fetch('/api/projects', { cache: 'no-store' });
    if (!res.ok) return '';
    const data = await res.json();
    const first = (data.projects || [])[0];
    return (first && first.path) || '';
  } catch (err) {
    return '';
  }
}

/** 节点质量：越关键/越异常越重，用于轨道半径、尺寸和星系质量。 */
function nodeMass(n, sys) {
  if (n.mass) return n.mass;
  let m = 0.8;
  if (n.shot) {
    m = n.status === 'block' ? 1.9 : (n.status === 'pass' ? 1.45 : 1.15);
  } else if (n.anchor) {
    m = 0.55;
  } else if (n.leg) {
    m = 1.6;
  } else if (n.agent) {
    m = 1.9;
  } else if (n.kind === 'node') {
    const rows = Object.fromEntries((n.rows || []).map((r) => [r[0], r[1]]));
    if (sys && sys.id === 'agents') m = 1.9;
    else if (sys && sys.id === 'knowledge') m = 1.3 + Math.min(1.1, Number(rows.chunks || 0) / 5000);
    else if (sys && sys.id === 'workflow') m = 1.2;
    else if (sys && sys.id === 'evidence') m = 0.45;
    else if (sys && sys.id === 'slots') m = 0.6;
    else m = 0.9;
  }
  n.mass = m;
  return m;
}

/** 星系绕共同质心排布：质量越大越靠内；角度用黄金角错开，避免共线。 */
function arrangeSystems(systems) {
  const order = systems.map((sys, i) => ({
    sys, i, mass: (sys.nodes || []).reduce((a, n) => a + nodeMass(n, sys), 2)
  })).sort((a, b) => b.mass - a.mass);
  order.forEach((it, rank) => {
    const angle = -0.7 + rank * 2.399963;
    const r = 14 + rank * 7;
    const y = Math.sin(angle * 1.3) * 3.5 + (rank % 2 ? 2.5 : -2.5);
    it.sys.center = new THREE.Vector3(Math.cos(angle) * r, y, Math.sin(angle) * r);
  });
}

/** 按质量分环落点：重节点进内环、变大；轻节点在外环做背景。 */
function layoutSystems(systems) {
  arrangeSystems(systems);
  systems.forEach((sys, si) => {
    sys.ringQuats = [];
    const nodes = (sys.nodes || []).slice().sort((a, b) => nodeMass(b, sys) - nodeMass(a, sys));
    const ringCount = Math.max(1, (sys.rings || [5]).length);
    const buckets = Array.from({ length: ringCount }, () => []);
    nodes.forEach((n, i) => {
      const ri = Math.min(ringCount - 1, Math.floor((i / Math.max(1, nodes.length)) * ringCount));
      buckets[ri].push(n);
      n.ringIndex = ri;
      const m = nodeMass(n, sys);
      n.sizeMul = clamp(0.70 + Math.sqrt(m / 1.3) * 0.95, 0.70, 2.40);
    });
    buckets.forEach((arr, ri) => {
      const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(
        sys.tilt[0] + ri * 0.09, sys.tilt[1] + ri * 0.13, ri * 0.10
      ));
      const r0 = sys.rings[ri] || 5;
      arr.forEach((n, j) => {
        const a = (j / Math.max(1, arr.length)) * Math.PI * 2 + ri * 0.7 + si * 0.4;
        const r = r0 * (0.94 + hash(si * 10 + ri * 3 + j) * 0.12);
        const local = new THREE.Vector3(
          Math.cos(a) * r,
          (hash(si * 17 + ri * 5 + j * 3) - 0.5) * 0.55,
          Math.sin(a) * r
        ).applyQuaternion(q);
        n.pos = local.clone().add(sys.center);
        n.sys = sys;
      });
      sys.ringQuats.push(q);
    });
  });
}

function buildModel(data, workflow, kb) {
  const b = data.batch || {};
  const cov = b.coverage || {};
  const shots = data.shots || {};
  const gate = data.gate || {};
  const batchDir = data.batch_dir || '';
  const gatePath = data.gate_path || '';
  const wfBatch = (workflow && workflow.batch_dir) || '';
  const normPath = (s) => String(s || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  const wfBatchMismatch = !!(wfBatch && batchDir && normPath(wfBatch) !== normPath(batchDir));
  const legMeta = {};
  (data.legs || []).forEach((x) => { if (x && x.id) legMeta[x.id] = x; });
  let passCount = 0;
  Object.keys(shots).forEach((sid) => {
    const v = (shots[sid] || {})['verdict.json'] || {};
    if (v.overall === 'PASS') passCount += 1;
  });

  const legs = Object.keys(cov).sort().map((id) => {
    const c = cov[id] || {};
    const meta = legMeta[id] || {};
    const ok = c.not_applicable ? true : (c.checked_n > 0 && c.M > 0);
    return {
      id, kind: 'node', label: id, sub: `T${c.T || 0} · M${c.M || 0}`,
      color: ok ? C.accent : C.amber, status: ok ? 'ok' : 'warn',
      baseSize: 0.50, sizeMul: 1.0,
      rows: [
        ['check', meta.check || '—'],
        ['node types', (meta.node_types || []).join(' / ') || '—'],
        ['T / M', `${c.T || 0} / ${c.M || 0}`],
        ['checked', c.checked_n || 0],
        ['镜数', c.shots || 0],
        ['N/A 镜', (c.not_applicable_shots || []).length],
        ['整腿 N/A', c.not_applicable ? '是' : '否']
      ]
    };
  });

  const shotNodes = Object.keys(shots).sort().map((id) => {
    const rec = shots[id] || {};
    const v = rec['verdict.json'] || {};
    const man = rec['manifest.json'] || {};
    const ok = v.overall === 'PASS';
    const c = v.canary || {};
    return {
      id, kind: 'node', label: id, sub: v.overall || '?',
      color: ok ? C.green : C.red, status: ok ? 'pass' : 'block',
      baseSize: 0.50, sizeMul: 1.0,
      rows: [
        ['判定', v.overall || '?'],
        ['nodes', (man.nodes || []).length],
        ['canary', (c.mutant_errors || 0) + ' / ' + (c.expected_mutants || 0) +
         ' · clean ' + (c.clean_errors || 0)],
        ['trace', String(v.trace_sha1 || '').slice(0, 10) || '—'],
        ['legs', Object.keys(v.legs || {}).length + ' 条腿']
      ],
      workbench: true
    };
  });

  const KIND_COLOR = { T: C.sky, M: C.amber, C: C.purple };
  const seen = {};
  const naShots = {};
  const resultMap = {};
  Object.keys(shots).forEach((sid) => {
    const rec = shots[sid] || {};
    const man = rec['manifest.json'] || {};
    (man.not_applicable || []).forEach((x) => {
      if (!x.leg) return;
      (naShots[x.leg] = naShots[x.leg] || new Set()).add(sid);
    });
    (man.nodes || []).forEach((n) => {
      const id = n.node_id;
      if (!id) return;
      seen[id] = seen[id] || {
        id, kind: n.kind, leg: n.leg, check: n.check || '', node_type: n.node_type || '', shots: 0
      };
      seen[id].shots += 1;
      if (!seen[id].check && n.check) seen[id].check = n.check;
    });
    const v = rec['verdict.json'] || {};
    (v.nodes || []).forEach((n) => {
      if (!n.node_id) return;
      const r = resultMap[n.node_id] = resultMap[n.node_id] || { ok: 0, bad: 0, results: {} };
      const res = n.result || 'unknown';
      r.results[res] = (r.results[res] || 0) + 1;
      if (res === 'ok') r.ok += 1; else r.bad += 1;
    });
  });
  const evidence = Object.keys(seen).sort().map((id) => {
    const n = seen[id];
    const total = Object.keys(shots).length;
    const na = naShots[n.leg] ? naShots[n.leg].size : 0;
    const expected = Math.max(0, total - na);
    const res = resultMap[id] || { ok: 0, bad: 0, results: {} };
    const verdictSeen = res.ok + res.bad;
    const verdictMissing = Math.max(0, n.shots - verdictSeen);
    const badKinds = Object.keys(res.results)
      .filter((k) => k !== 'ok')
      .map((k) => k + ':' + res.results[k]).join(' / ') || '—';
    const status = res.bad ? 'block'
      : ((n.shots === expected && verdictMissing === 0) ? 'ok' : 'warn');
    return {
      id, kind: 'node', label: id, sub: `${n.shots}/${expected} 镜`,
      color: status === 'block' ? C.red : (KIND_COLOR[n.kind] || C.accent),
      status,
      baseSize: 0.44, sizeMul: 0.8,
      ringIndex: n.kind === 'T' ? 0 : (n.kind === 'M' ? 1 : 2),
      rows: [
        ['kind', n.kind || '—'], ['leg', n.leg || '—'], ['check', n.check || '—'],
        ['镜数', n.shots + ' / ' + expected + (na ? `（${na} 镜 N/A）` : '')],
        ['结果', 'ok ' + res.ok + ' · 异常 ' + res.bad + (verdictMissing ? ' · 缺 verdict ' + verdictMissing : '')],
        ['异常明细', badKinds], ['类型', n.node_type || '—']
      ]
    };
  });

  const evidenceWarn = evidence.filter((n) => n.status === 'warn').length;
  const evidenceBlock = evidence.filter((n) => n.status === 'block').length;
  const evidenceNa = Object.keys(naShots).length;

  let assetN = 0;
  let sceneN = 0;
  let l7Tn = 0;
  let l8Tn = 0;
  Object.keys(shots).forEach((sid) => {
    const rec = shots[sid] || {};
    assetN += (rec['assets_clean.json'] || []).length;
    sceneN += (rec['scenes_clean.json'] || []).length;
    const man = rec['manifest.json'] || {};
    (man.nodes || []).forEach((n) => {
      if (n.leg === 'L7' && n.kind === 'T') l7Tn += 1;
      if (n.leg === 'L8' && n.kind === 'T') l8Tn += 1;
    });
  });
  let cleanErr = 0;
  let unexpectedN = 0;
  Object.keys(shots).forEach((sid) => {
    const v = (shots[sid] || {})['verdict.json'] || {};
    cleanErr += ((v.canary || {}).clean_errors || 0);
    unexpectedN += (v.unexpected_errors || []).length;
  });
  const batchFailN = (b.failures || []).length;
  const signalN = cleanErr + unexpectedN + batchFailN;
  const gateKnown = !!(gate && Object.keys(gate).length);
  const gateSkipped = gateKnown && !!gate.skipped;
  const gateOk = gateKnown && gate.ok === true;
  const gateSub = !gateKnown ? '未读' : (gateSkipped ? '跳过' : (gateOk ? 'PASS' : 'FAIL'));
  const gateStatus = !gateKnown ? 'warn' : (gateSkipped ? 'warn' : (gateOk ? 'ok' : 'block'));
  const gateColor = !gateKnown ? C.amber : (gateSkipped ? C.amber : (gateOk ? C.green : C.red));

  const slotNodes = [
    { id: 'assets', kind: 'node', label: '资产', sub: String(assetN),
      color: C.sky, status: assetN ? 'ok' : 'warn', baseSize: 0.44, sizeMul: 0.9,
      rows: [['资产记录', assetN], ['L7 T 节点', l7Tn],
             ['L7 checked', (cov.L7 || {}).checked_n || 0],
             ['说明', '角色/场景裁切与暂存；记录数来自 assets_clean.json']] },
    { id: 'scenes', kind: 'node', label: '场景', sub: String(sceneN),
      color: C.purple, status: sceneN ? 'ok' : 'warn', baseSize: 0.44, sizeMul: 0.9,
      rows: [['场景记录', sceneN], ['L8 T 节点', l8Tn],
             ['L8 checked', (cov.L8 || {}).checked_n || 0],
             ['说明', '场景状态锚与 base 中性；记录数来自 scenes_clean.json']] },
    { id: 'gate', kind: 'node', label: '跑前闸', sub: gateSub,
      color: gateColor, status: gateStatus, baseSize: 0.44, sizeMul: 0.9,
      rows: [['判定', gateSub], ['批次', (gate.info || {}).batch_dir || '—'],
             ['文件', gatePath || '—'],
             ['reasons', (gate.reasons || []).length],
             ['说明', gateKnown ? '来自 --gate 指定的闸结果' : '未提供 --gate']] },
    { id: 'signals', kind: 'node', label: '信号', sub: String(signalN),
      color: signalN ? C.amber : C.muted, status: signalN ? 'warn' : 'ok',
      baseSize: 0.44, sizeMul: 0.9,
      rows: [['clean error', cleanErr], ['非预期错误', unexpectedN],
             ['批次 failures', batchFailN], ['说明', 'clean/异常/批级失败聚合']] }
  ];

  const WF_COLOR = { ok: C.green, block: C.red, error: C.red, skipped: C.muted, pending: C.amber };
  const WF_STATUS = { ok: '通过', block: '阻断', error: '错误', skipped: '跳过', pending: '待跑' };
  const wfNodes = ((workflow && workflow.stages) || []).map((st) => {
    const status = st.status || 'pending';
    return {
      id: 'wf-' + st.id, kind: 'node', label: st.label || st.id,
      sub: WF_STATUS[status] || status,
      color: WF_COLOR[status] || C.amber,
      status: status === 'ok' ? 'ok'
        : ((status === 'block' || status === 'error') ? 'block'
          : (status === 'skipped' ? 'muted' : 'warn')),
      baseSize: 0.46, sizeMul: 0.85,
      rows: [
        ['阶段', st.label || st.id],
        ['状态', WF_STATUS[status] || status],
        ['耗时', st.duration_s == null ? '—' : st.duration_s + 's'],
        ['摘要', st.summary || st.reason || '—'],
        ['产物', st.artifacts ? Object.keys(st.artifacts).join(' / ') : '—']
      ]
    };
  });

  const AGENT_COLOR = { accent: C.accent, sky: C.sky, muted: C.muted, red: C.red };
  const agentNodes = (((data.agents || {}).stars) || []).map((a) => {
    const isCur = workflow && workflow.agent_id === a.agent_id;
    return {
      id: 'agent-' + a.agent_id,
      kind: 'agent',
      label: a.agent_id,
      sub: `${a.runs} run${a.runs === 1 ? '' : 's'}`,
      color: AGENT_COLOR[a.color] || C.accent,
      status: !a.valid ? 'block' : (a.archived ? 'warn' : 'ok'),
      baseSize: 0.72 + 0.42 * (a.magnitude || 0),
      sizeMul: 1.45,
      isAgent: true,
      agentId: a.agent_id,
      rows: [
        ['状态', a.archived ? '归档' : 'active'],
        ['owner', a.owner || '—'],
        ['运行', `${a.runs} 次 · PASS ${a.pass} / BLOCK ${a.block}`],
        ['镜头', String(a.shots)],
        ['加入', a.joined_at || '—'],
        ['最近', a.last_seen || '—'],
        ['本批次', isCur ? '是（当前 workflow）' : '否'],
        ['scopes', (a.scopes || []).length + ' 项']
      ]
    };
  });

  const evidenceSub = `${evidence.length} 节点 · T/M/C`
    + (evidenceBlock ? ` · ${evidenceBlock} 异常` : '')
    + (evidenceWarn ? ` · ${evidenceWarn} 待补` : '')
    + (evidenceNa ? ` · ${evidenceNa} 腿含 N/A` : '');
  const KB_COLOR = {
    core: C.accent, project: C.green, skills: C.amber,
    memory: C.purple, archive: C.muted
  };
  const kbCols = (kb && kb.collections) || [];
  const kbNodes = kbCols.map((c) => {
    const status = c.status === 'block' ? 'block'
      : (c.status === 'missing' ? 'warn' : 'ok');
    const color = status === 'block' ? C.red
      : (status === 'warn' ? C.amber : (KB_COLOR[c.name] || C.sky));
    const retro = c.retrieval || {};
    return {
      id: 'kb-' + c.name, kind: 'node', label: c.name,
      sub: (c.chunks || 0) + ' chunks',
      color, status, baseSize: 0.52, sizeMul: 0.95,
      kb: c.name, chunks: c.chunks || 0, files: c.files || 0,
      rows: [
        ['文件', c.files || 0], ['chunks', c.chunks || 0],
        ['FTS', c.fts_chunks || 0], ['去重引用', c.dupe_refs || 0],
        ['audit', c.audit || 'missing'],
        ['retrieval', retro.summary || retro.status || '—'],
        ['目录', c.path || '—']
      ]
    };
  });
  const kbChunks = kbNodes.reduce((a, n) => a + (n.chunks || 0), 0);

  const systems = [
    {
      id: 'legs', kind: 'system', label: '八验环', fullLabel: '八验星环', sub: `${legs.length} 条腿`, linkBatch: true,
      status: legs.some((n) => n.status === 'warn') ? 'warn' : 'ok',
      color: C.accent, center: new THREE.Vector3(-25, 2.5, -6),
      rings: [3.9, 5.7, 7.4], tilt: [0.42, 0.10], nodes: legs
    },
    {
      id: 'shots', kind: 'system', label: '分镜带', fullLabel: '分镜星带', sub: `${shotNodes.length} 镜 · ${passCount} PASS`, linkBatch: true,
      status: passCount === shotNodes.length ? 'ok' : 'block',
      color: passCount === shotNodes.length ? C.green : C.red,
      center: new THREE.Vector3(0, -3.5, 22),
      rings: [4.3, 6.2, 8.1], tilt: [0.30, -0.22], nodes: shotNodes
    },
    {
      id: 'slots', kind: 'system', label: '扩展区', fullLabel: '扩展星区', sub: `${slotNodes.length} 个槽`, linkBatch: true,
      status: slotNodes.some((n) => n.status === 'warn') ? 'warn' : 'ok',
      color: C.purple, center: new THREE.Vector3(24, 4.5, -8),
      rings: [3.8, 5.7], tilt: [0.55, 0.28], nodes: slotNodes
    },
    {
      id: 'evidence', kind: 'system', label: '证据云', fullLabel: '证据星云', sub: evidenceSub, linkBatch: true,
      status: evidenceBlock ? 'block' : (evidenceWarn ? 'warn' : 'ok'),
      color: evidenceBlock ? C.red : (evidenceWarn ? C.amber : C.sky),
      center: new THREE.Vector3(0, 14, -34),
      rings: [7.0, 9.8, 12.6], tilt: [0.58, -0.36], nodes: evidence
    }
  ];

  if (wfNodes.length) {
    const wfOverall = (workflow && workflow.overall) || '?';
    const wfSub = `${wfOverall} · ${wfNodes.length} 阶段` + (wfBatchMismatch ? ' · 批次≠看板' : '');
    systems.push({
      id: 'workflow', kind: 'system', label: '工序轨', fullLabel: '工序星轨', sub: wfSub, linkBatch: !!wfBatch && !wfBatchMismatch,
      status: wfBatchMismatch ? 'warn' : (wfOverall === 'PASS' ? 'ok' : (wfOverall === 'BLOCK' ? 'block' : 'warn')),
      color: wfBatchMismatch ? C.amber : (wfOverall === 'PASS' ? C.green : (wfOverall === 'BLOCK' ? C.red : C.amber)),
      center: new THREE.Vector3(-26, -12, 20),
      rings: [4.2, 6.0], tilt: [0.40, -0.20], nodes: wfNodes
    });
  }

  if (agentNodes.length) {
    const agCounts = (data.agents || {}).counts || {};
    const agSub = `${agentNodes.length} 个 agent · ${agCounts.total_runs || 0} 运行`
      + (agCounts.hidden ? ` · ${agCounts.hidden} 隐藏` : '')
      + (agCounts.orphans ? ` · ${agCounts.orphans} 孤儿` : '');
    systems.push({
      id: 'agents', kind: 'system', label: '主序群', fullLabel: '主序星群', sub: agSub, linkBatch: false,
      status: agentNodes.some((n) => n.status === 'block') ? 'block'
        : (agentNodes.some((n) => n.status === 'warn') ? 'warn' : 'ok'),
      color: C.accent, center: new THREE.Vector3(26, -11, 22),
      rings: [5.2, 7.6], tilt: [0.36, 0.24], nodes: agentNodes
    });
  }

  if (kbNodes.length) {
    systems.push({
      id: 'knowledge', kind: 'system', label: '知识云', fullLabel: '知识星云',
      sub: `${kbNodes.length} collections · ${kbChunks} chunks`, linkBatch: false,
      status: kbNodes.some((n) => n.status === 'block') ? 'block'
        : (kbNodes.some((n) => n.status === 'warn') ? 'warn' : 'ok'),
      color: kbNodes.some((n) => n.status === 'block') ? C.red
        : (kbNodes.some((n) => n.status === 'warn') ? C.amber : C.purple),
      center: new THREE.Vector3(28, 14, 10),
      rings: [3.8, 5.6], tilt: [0.44, -0.18], nodes: kbNodes
    });
  }

  layoutSystems(systems);

  return {
    batch: b, gate, systems, legs, shots: shotNodes, slots: slotNodes, evidence,
    workflow: workflow || null, workflowStages: wfNodes.length,
    agentCount: agentNodes.length,
    passCount, shotCount: Object.keys(shots).length,
    overall: b.overall || '?', failures: (b.failures || []).length,
    batchDir: data.batch_dir || '',
    workflowBatch: wfBatch, workflowMismatch: wfBatchMismatch,
    evidenceNa, evidenceBlock, assetN, sceneN, signalN,
    kb: kb || null, kbCount: kbNodes.length, kbChunks
  };
}

/* ---------------- scene ---------------- */

let model = null;
let renderer, scene, camera, controls, composer, gradePass, labelRenderer;
let sky, skyMat, bloom;
let coreSprite, coreInner, coreFlare, coreRing, coreRing2, coreLabel, coreGroup;
let nodeMeshes = [];
let systemCores = [];
let pulses = [];
let labels = [];
let selected = null;

/* ---------------- 运行反馈：镜头节点闪烁 ---------------- */

const shotFlash = new Map();   // shot id -> { state, at }
let shotIndex = null;

function ensureShotIndex() {
  if (shotIndex) return shotIndex;
  if (!model) return new Map();
  shotIndex = new Map();
  (model && model.systems || []).forEach((sys) => {
    (sys.nodes || []).forEach((n) => {
      if (n && n.shot) shotIndex.set(n.id, n);
    });
  });
  return shotIndex;
}

function paintFlashLabel(node, state) {
  const el = node && node.labelObj && (node.labelObj.element || node.labelObj.el);
  if (!el) return;
  el.classList.remove('flash-run', 'flash-done', 'flash-fail');
  if (state === 'running') el.classList.add('flash-run');
  else if (state === 'done') el.classList.add('flash-done');
  else if (state === 'fail') el.classList.add('flash-fail');
}

function setShotFlash(id, state, instant) {
  if (!id) return;
  const norm = (state === 'done' || state === 'pass') ? 'done'
    : ((state === 'failed' || state === 'block') ? 'fail'
      : ((state === 'running' || state === 'waiting') ? 'running' : ''));
  if (!norm) {
    shotFlash.delete(id);
    const n = ensureShotIndex().get(id);
    if (n) paintFlashLabel(n, '');
    return;
  }
  const at = performance.now() - (instant ? 5000 : 0);
  shotFlash.set(id, { state: norm, at });
  const n = ensureShotIndex().get(id);
  if (n) paintFlashLabel(n, norm);
}

function clearShotFlash() {
  shotFlash.forEach((v, id) => {
    const n = ensureShotIndex().get(id);
    if (n) {
      paintFlashLabel(n, '');
      if (n.mesh && n.mesh.material && n.mesh.material.uniforms
          && n.mesh.material.uniforms.uFlash) {
        n.mesh.material.uniforms.uFlash.value = 0;
      }
    }
  });
  shotFlash.clear();
}

function applyFlashSnapshot(detail) {
  const shots = detail && detail.shots;
  if (!shots) return;
  // 快照代表当前任务的全量状态：先清掉上一轮的残留，再按快照上色。
  clearShotFlash();
  const index = ensureShotIndex();
  Object.keys(shots).forEach((id) => {
    if (index.has(id)) setShotFlash(id, shots[id], true);
  });
}

function updateShotFlash(now) {
  if (!shotFlash.size) return;
  const index = ensureShotIndex();
  const t = now * 0.001;
  shotFlash.forEach((st, id) => {
    const n = index.get(id);
    const u = n && n.mesh && n.mesh.material && n.mesh.material.uniforms;
    if (!u || !u.uFlash) return;
    let flash = 0;
    let color = 0x5eead4;
    if (st.state === 'running') {
      flash = 0.30 + 0.24 * (0.5 + 0.5 * Math.sin(t * 3.2));
      color = 0x5eead4;
    } else if (st.state === 'done') {
      const age = (now - st.at) / 1000;
      if (age < 1.2) {
        flash = (1 - age / 1.2) * (0.55 + 0.45 * Math.abs(Math.sin(age * 16)));
        color = 0xbfffe8;
      }
    } else if (st.state === 'fail') {
      flash = 0.24 + 0.20 * (0.5 + 0.5 * Math.sin(t * 2.0));
      color = 0xff6b6b;
    }
    u.uFlash.value = flash;
    u.uFlashColor.value.setHex(color);
  });
}

window.addEventListener('fanxing:job', (e) => {
  const ev = e.detail || {};
  if (ev.type === 'job') clearShotFlash();
  else if (ev.type === 'status'
           && (ev.status === 'cancelled' || ev.status === 'interrupted')) {
    clearShotFlash();
  } else if (ev.type === 'shot') setShotFlash(ev.shot, ev.state, false);
});
window.addEventListener('fanxing:snapshot', (e) => applyFlashSnapshot(e.detail));
let hovered = null;
let tween = null;
let cruise = true;
let idleTimer = null;
let skyYaw = 0;
let deepSkyTex = null;

const HOME_POS = new THREE.Vector3(50, 26, 60);
const HOME_TARGET = new THREE.Vector3(0, 1, 2);

function initRenderer() {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
  renderer.setClearColor(C.bg, 1);
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.domElement.setAttribute('aria-label', '批次三维星图：拖动旋转，滚轮缩放，单击节点，双击聚焦');
  sceneHost.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(44, 1, 0.1, 500);
  camera.position.copy(HOME_POS);
  scene.add(camera);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(HOME_TARGET);
  controls.enableDamping = true;
  controls.dampingFactor = 0.055;
  controls.enablePan = false;
  controls.rotateSpeed = 0.55;
  controls.zoomSpeed = 0.75;
  controls.minDistance = 3.2;
  controls.maxDistance = 200;
  controls.minPolarAngle = 0.08;
  controls.maxPolarAngle = Math.PI - 0.08;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.32;
  controls.zoomToCursor = true;
  controls.update();

  labelRenderer = new CSS2DRenderer({ element: labelsHost });
  labelRenderer.domElement.style.position = 'absolute';
  labelRenderer.domElement.style.inset = '0';
  labelRenderer.domElement.style.pointerEvents = 'none';

  const rt = renderer.capabilities.isWebGL2
    ? new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 })
    : null;
  composer = rt ? new EffectComposer(renderer, rt) : new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.82, 0.60, 0.72);
  composer.addPass(bloom);
  gradePass = new ShaderPass(GRADE_SHADER);
  composer.addPass(gradePass);

  controls.addEventListener('start', noteInteraction);
  window.addEventListener('resize', resize);
  if (window.ResizeObserver) new ResizeObserver(resize).observe(sceneHost);
}

function makeSky() {
  const geo = new THREE.PlaneGeometry(1, 1);
  skyMat = new THREE.ShaderMaterial({
    uniforms: {
      uRes: { value: new THREE.Vector2(1, 1) },
      uTime: { value: 0 },
      uCam: { value: new THREE.Vector2(0, 0) }
    },
    vertexShader: SKY_VS,
    fragmentShader: SKY_FS,
    depthTest: false,
    depthWrite: false,
    transparent: false
  });
  sky = new THREE.Mesh(geo, skyMat);
  sky.position.set(0, 0, -1);
  sky.renderOrder = -1000;
  sky.frustumCulled = false;
  camera.add(sky);

  // 真实深空底图（NASA Deep Star Maps 2020 + Milky Way，公共领域，本地 4K JPEG）。
  // 加载成功就替换程序化天空；失败则保留程序化 fallback。
  new THREE.TextureLoader().load('/sky/deepspace_2020_4k.jpg', (tex) => {
    tex.mapping = THREE.EquirectangularReflectionMapping;
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.minFilter = THREE.LinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.generateMipmaps = false;
    tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    scene.background = tex;
    deepSkyTex = tex;
    sky.visible = false;
  }, undefined, () => { /* 保留程序化天空 */ });
}

function pointsCloud(count, radiusMin, radiusMax, size, tint, opacity) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const col = new THREE.Color(tint);
  for (let i = 0; i < count; i++) {
    const u = Math.random() * 2 - 1;
    const phi = Math.random() * Math.PI * 2;
    const s = Math.sqrt(1 - u * u);
    const r = radiusMin + Math.random() * (radiusMax - radiusMin);
    positions[i * 3] = Math.cos(phi) * s * r;
    positions[i * 3 + 1] = u * r;
    positions[i * 3 + 2] = Math.sin(phi) * s * r;
    const f = 0.65 + Math.random() * 0.35;
    colors[i * 3] = col.r * f;
    colors[i * 3 + 1] = col.g * f;
    colors[i * 3 + 2] = col.b * f;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const mat = new THREE.PointsMaterial({
    size, map: TEX_STAR, transparent: true, opacity, vertexColors: true,
    blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
  });
  return new THREE.Points(geo, mat);
}

const twinkleMats = [];
let bandGroup = null;
let dustGroup = null;

function starfield(count, rMin, rMax, sizeMul, tint, opacity) {
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const siz = new Float32Array(count);
  const pha = new Float32Array(count);
  const base = new THREE.Color(tint);
  for (let i = 0; i < count; i++) {
    const u = Math.random() * 2 - 1;
    const phi = Math.random() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    const r = rMin + Math.random() * (rMax - rMin);
    pos[i * 3] = Math.cos(phi) * sq * r;
    pos[i * 3 + 1] = u * r;
    pos[i * 3 + 2] = Math.sin(phi) * sq * r;
    const f = 0.55 + Math.random() * 0.45;
    col[i * 3] = base.r * f;
    col[i * 3 + 1] = base.g * f;
    col[i * 3 + 2] = base.b * f;
    siz[i] = (0.8 + Math.random() * 2.0) * sizeMul;
    pha[i] = Math.random() * Math.PI * 2;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
  geo.setAttribute('aSize', new THREE.BufferAttribute(siz, 1));
  geo.setAttribute('aPhase', new THREE.BufferAttribute(pha, 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uMap: { value: TEX_STAR }, uOpacity: { value: opacity } },
    vertexShader: `
      uniform float uTime;
      attribute vec3 aColor;
      attribute float aSize;
      attribute float aPhase;
      varying vec3 vColor;
      void main() {
        vColor = aColor;
        float tw = 0.72 + 0.28 * sin(uTime * 0.9 + aPhase);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = clamp(aSize * (260.0 / max(1.0, -mv.z)) * tw, 0.6, 7.0);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform sampler2D uMap;
      uniform float uOpacity;
      varying vec3 vColor;
      void main() {
        vec4 t = texture2D(uMap, gl_PointCoord);
        gl_FragColor = vec4(vColor, t.a * uOpacity);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  twinkleMats.push(mat);
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  return pts;
}

function makeSectorGrid() {
  const g = new THREE.Group();
  const rings = [55, 95, 150];
  rings.forEach((r, i) => {
    const pts = [];
    for (let k = 0; k <= 256; k++) {
      const a = (k / 256) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r));
    }
    const line = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({
        color: 0x2b4b60, transparent: true, opacity: 0.16 - i * 0.035, depthWrite: false
      })
    );
    g.add(line);
    for (let k = 0; k < 72; k++) {
      const a = (k / 72) * Math.PI * 2;
      const r0 = r;
      const r1 = r + (k % 6 === 0 ? 2.0 : 0.8);
      const tick = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(Math.cos(a) * r0, 0, Math.sin(a) * r0),
          new THREE.Vector3(Math.cos(a) * r1, 0, Math.sin(a) * r1)
        ]),
        new THREE.LineBasicMaterial({
          color: 0x2b4b60, transparent: true, opacity: 0.18 - i * 0.04, depthWrite: false
        })
      );
      g.add(tick);
    }
  });
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(Math.cos(a) * 26, 0, Math.sin(a) * 26),
        new THREE.Vector3(Math.cos(a) * 150, 0, Math.sin(a) * 150)
      ]),
      new THREE.LineBasicMaterial({
        color: 0x2b4b60, transparent: true, opacity: 0.055, depthWrite: false
      })
    );
    g.add(line);
  }
  scene.add(g);
}

function makeBackgroundCities() {
  const colors = [0xbfd8ff, 0xffffff, 0xc9b9ff, 0x9fe8d8, 0xffd2a8];
  for (let i = 0; i < 42; i++) {
    const u = Math.random() * 2 - 1;
    const phi = Math.random() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    const r = 140 + Math.random() * 200;
    const pos = new THREE.Vector3(
      Math.cos(phi) * sq * r,
      u * r * 0.72,
      Math.sin(phi) * sq * r
    );
    const color = colors[i % colors.length];
    const n = 35 + Math.floor(Math.random() * 55);
    const cloud = pointsCloud(n, 0.6, 2.2 + Math.random() * 4.2, 0.24 + Math.random() * 0.12, color, 0.42 + Math.random() * 0.28);
    cloud.position.copy(pos);
    scene.add(cloud);
    if (i % 3 === 0) {
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({
        map: TEX_GLOW, color, transparent: true, opacity: 0.10,
        blending: THREE.AdditiveBlending, depthWrite: false
      }));
      glow.position.copy(pos);
      glow.scale.setScalar(5 + Math.random() * 7);
      scene.add(glow);
    }
  }
  for (let i = 0; i < 10; i++) {
    const color = colors[i % colors.length];
    const pos = new THREE.Vector3(
      120 + Math.random() * 190,
      -90 + Math.random() * 180,
      -80 - Math.random() * 180
    );
    const cloud = pointsCloud(45 + Math.floor(Math.random() * 40), 0.6, 2.4 + Math.random() * 3.4, 0.26, color, 0.42);
    cloud.position.copy(pos);
    scene.add(cloud);
  }
}

function makeStars() {
  // 真实星图负责远景恒星/银河；这里只留少量近场尘埃做视差，避免双份星点。
  scene.add(starfield(520, 30, 120, 0.42, 0xcfe0ff, 0.10));
  dustGroup = new THREE.Group();
  dustGroup.add(starfield(220, 22, 78, 0.42, 0x9fc7e8, 0.10));
  scene.add(dustGroup);
}

function makeGalacticBand() {
  const N = 10000;
  const pos = new Float32Array(N * 3);
  const col = new Float32Array(N * 3);
  const c1 = new THREE.Color(0x9fc4ff);
  const c2 = new THREE.Color(0xd9c6ff);
  const c = new THREE.Color();
  for (let i = 0; i < N; i++) {
    const r = 150 + Math.pow(Math.random(), 0.62) * 340;
    const a = Math.random() * Math.PI * 2;
    const y = (Math.random() + Math.random() + Math.random() - 1.5) * 13 * (1 - r / 500);
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = y;
    pos[i * 3 + 2] = Math.sin(a) * r;
    const f = 0.22 + Math.random() * 0.65;
    c.copy(c1).lerp(c2, Math.random());
    col[i * 3] = c.r * f;
    col[i * 3 + 1] = c.g * f;
    col[i * 3 + 2] = c.b * f;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const mat = new THREE.PointsMaterial({
    size: 0.56, map: TEX_STAR, transparent: true, opacity: 0.46, vertexColors: true,
    blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
  });
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  bandGroup = new THREE.Group();
  bandGroup.rotation.set(0.82, 0.16, 0.30);
  bandGroup.add(pts);
  scene.add(bandGroup);
}

function makeDistantFields() {
  const colors = [C.accent, C.sky, C.purple, 0xffa477, 0x8fb7ff];
  for (let i = 0; i < 10; i++) {
    const u = Math.random() * 2 - 1;
    const phi = Math.random() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    const r = 210 + Math.random() * 150;
    const pos = new THREE.Vector3(Math.cos(phi) * sq * r, u * r * 0.8, Math.sin(phi) * sq * r);
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({
      map: TEX_GLOW, color: colors[i % colors.length], transparent: true,
      opacity: 0.05 + Math.random() * 0.05,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    spr.position.copy(pos);
    spr.scale.setScalar(50 + Math.random() * 80);
    scene.add(spr);
  }

  for (let i = 0; i < 3; i++) {
    const u = Math.random() * 2 - 1;
    const phi = Math.random() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    const r = 270 + Math.random() * 110;
    const gal = new THREE.Sprite(new THREE.SpriteMaterial({
      map: TEX_GALAXY, color: 0x9fb7e8, transparent: true,
      opacity: 0.13 + Math.random() * 0.06,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    gal.material.rotation = Math.random() * Math.PI;
    gal.position.set(Math.cos(phi) * sq * r, u * r * 0.65, Math.sin(phi) * sq * r);
    gal.scale.set(24 + Math.random() * 26, 10 + Math.random() * 12, 1);
    scene.add(gal);
  }

  [
    { p: [270, -46, -250], sc: 270, c: 0x6f8cff, o: 0.055 },
    { p: [190, 130, -300], sc: 210, c: 0xb07fff, o: 0.045 },
    { p: [330, -110, 40], sc: 230, c: 0x3fb3c9, o: 0.040 },
    { p: [-260, -90, -300], sc: 190, c: 0x5f7fff, o: 0.035 }
  ].forEach((h) => {
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({
      map: TEX_GLOW, color: h.c, transparent: true, opacity: h.o,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    spr.position.set(h.p[0], h.p[1], h.p[2]);
    spr.scale.setScalar(h.sc);
    scene.add(spr);
  });

  [
    { p: [330, -26, -270], sx: 150, sy: 55, o: 0.16 },
    { p: [-250, 96, -330], sx: 95, sy: 34, o: 0.12 },
    { p: [230, 170, -260], sx: 70, sy: 26, o: 0.10 }
  ].forEach((g) => {
    const gal = new THREE.Sprite(new THREE.SpriteMaterial({
      map: TEX_GALAXY, color: 0xcfe0ff, transparent: true, opacity: g.o,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    gal.position.set(g.p[0], g.p[1], g.p[2]);
    gal.scale.set(g.sx, g.sy, 1);
    gal.material.rotation = -0.4;
    scene.add(gal);
  });

  for (let i = 0; i < 10; i++) {
    const u = Math.random() * 2 - 1;
    const phi = Math.random() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    const r = 150 + Math.random() * 130;
    const pos = new THREE.Vector3(Math.cos(phi) * sq * r, u * r * 0.7, Math.sin(phi) * sq * r);
    const cloud = pointsCloud(180, 0.8, 8.5, 0.38, colors[i % colors.length], 0.66);
    cloud.position.copy(pos);
    scene.add(cloud);
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: TEX_GLOW, color: colors[i % colors.length], transparent: true,
      opacity: 0.14, blending: THREE.AdditiveBlending, depthWrite: false
    }));
    glow.position.copy(pos);
    glow.scale.setScalar(15 + Math.random() * 12);
    scene.add(glow);
  }
}


function makeBatchCore() {
  coreGroup = new THREE.Group();
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({
    map: TEX_GLOW, color: C.accent, transparent: true, opacity: 0.78,
    blending: THREE.AdditiveBlending, depthWrite: false
  }));
  halo.scale.setScalar(5.6);
  coreGroup.add(halo);

  const inner = new THREE.Sprite(new THREE.SpriteMaterial({
    map: TEX_GLOW, color: 0xffffff, transparent: true, opacity: 0.82,
    blending: THREE.AdditiveBlending, depthWrite: false
  }));
  inner.scale.setScalar(1.15);
  coreGroup.add(inner);
  coreInner = inner;

  const flare = new THREE.Sprite(new THREE.SpriteMaterial({
    map: TEX_FLARE, color: C.accent, transparent: true, opacity: 0.30,
    blending: THREE.AdditiveBlending, depthWrite: false
  }));
  flare.scale.setScalar(14);
  flare.material.rotation = 0.36;
  coreGroup.add(flare);
  coreFlare = flare;

  const ringMat = new THREE.MeshBasicMaterial({
    color: C.accent, transparent: true, opacity: 0.42, side: THREE.DoubleSide, depthWrite: false
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(2.5, 2.58, 96), ringMat);
  ring.rotation.x = -Math.PI / 2;
  coreGroup.add(ring);
  coreRing = ring;

  const ring2 = new THREE.Mesh(new THREE.RingGeometry(3.2, 3.24, 96), new THREE.MeshBasicMaterial({
    color: C.accent, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false
  }));
  ring2.rotation.x = -Math.PI / 2.2;
  coreGroup.add(ring2);
  coreRing2 = ring2;

  scene.add(coreGroup);
  coreSprite = halo;
  coreSprite.userData.pick = { kind: 'batch' };
  return coreGroup;
}

function addDustBand(sys, group, radius, quat, phase) {
  const count = 360;
  const pos = new Float32Array(count * 3);
  let n = 0;
  for (let i = 0; i < count; i += 1) {
    const a = Math.random() * Math.PI * 2;
    // 缺口：不是完整圆环，避免“画上去的线”感。
    if (Math.sin(a * 2.7 + phase) < -0.25) continue;
    const r = radius + (Math.random() - 0.5) * 0.8;
    const y = (Math.random() - 0.5) * 0.32;
    const v = new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r).applyQuaternion(quat);
    pos[n * 3] = v.x;
    pos[n * 3 + 1] = v.y;
    pos[n * 3 + 2] = v.z;
    n += 1;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos.subarray(0, n * 3), 3));
  const mat = new THREE.PointsMaterial({
    map: TEX_GLOW, color: sys.color, size: 0.28, transparent: true,
    opacity: 0.20, depthWrite: false, blending: THREE.AdditiveBlending,
    sizeAttenuation: true
  });
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  group.add(pts);
  sys.dustBands.push({ obj: pts, base: 0.20 });
}

function addLightArc(sys, group, radius, quat, start, length, opacity) {
  const geo = new THREE.RingGeometry(radius - 0.05, radius + 0.05, 96, 1, start, length);
  const mat = new THREE.MeshBasicMaterial({
    color: sys.color, transparent: true, opacity,
    side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.quaternion.premultiply(quat);
  mesh.frustumCulled = false;
  group.add(mesh);
  sys.arcs.push({ mesh, base: opacity });
}

function makeSystem(sys) {
  const g = new THREE.Group();
  g.position.copy(sys.center);

  const halo = new THREE.Sprite(new THREE.SpriteMaterial({
    map: TEX_GLOW, color: sys.color, transparent: true, opacity: 0.56,
    blending: THREE.AdditiveBlending, depthWrite: false
  }));
  halo.scale.setScalar(3.0);
  halo.userData.baseScale = 3.0;
  halo.userData.pick = sys;
  g.add(halo);

  const inner = new THREE.Sprite(new THREE.SpriteMaterial({
    map: TEX_GLOW, color: 0xffffff, transparent: true, opacity: 0.34,
    blending: THREE.AdditiveBlending, depthWrite: false
  }));
  inner.scale.setScalar(0.46);
  g.add(inner);
  sys.inner = inner;

  const flare = new THREE.Sprite(new THREE.SpriteMaterial({
    map: TEX_FLARE, color: sys.color, transparent: true, opacity: 0.12,
    blending: THREE.AdditiveBlending, depthWrite: false
  }));
  flare.scale.setScalar(7.5);
  flare.material.rotation = 0.4;
  g.add(flare);
  sys.flare = flare;

  const fog = new THREE.Sprite(new THREE.SpriteMaterial({
    map: TEX_GLOW, color: sys.color, transparent: true, opacity: 0.05,
    blending: THREE.AdditiveBlending, depthWrite: false
  }));
  fog.scale.setScalar(16);
  g.add(fog);

  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(sys.tilt[0], sys.tilt[1], 0));
  const ring = new THREE.Mesh(new THREE.RingGeometry(1.18, 1.24, 80), new THREE.MeshBasicMaterial({
    color: sys.color, transparent: true, opacity: 0.32, side: THREE.DoubleSide, depthWrite: false
  }));
  ring.rotation.x = -Math.PI / 2;
  ring.quaternion.premultiply(q);
  g.add(ring);
  sys.coreRing = ring;

  // 环线换成「尘带 + 断裂光弧」：粒子有密度差和缺口，弧段不闭合，悬停/选中再亮。
  sys.arcs = [];
  sys.dustBands = [];
  const ringRadii = (sys.rings || []).filter((r) => r > 0);
  if (ringRadii.length && sys.ringQuats && sys.ringQuats.length) {
    const outer = ringRadii[ringRadii.length - 1];
    const inner = ringRadii[0];
    const qOuter = sys.ringQuats[sys.ringQuats.length - 1] || q;
    const qInner = sys.ringQuats[0] || q;
    addDustBand(sys, g, inner, qInner, 0.7);
    addDustBand(sys, g, outer, qOuter, 2.1);
    addLightArc(sys, g, outer, qOuter, 0.22, 1.18, 0.10);
    addLightArc(sys, g, outer, qOuter, 2.42, 0.82, 0.065);
  }

  // 环线加回来：细线只做结构骨架，透明度和尘带/光弧分开，避免又变成线框。
  sys.ringQuats.forEach((rq, ri) => {
    const rr = (sys.rings || [])[ri];
    if (!rr) return;
    const pts = [];
    for (let k = 0; k <= 160; k += 1) {
      const a = (k / 160) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * rr, 0, Math.sin(a) * rr).applyQuaternion(rq));
    }
    const line = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({
        color: sys.color, transparent: true, opacity: 0.12, depthWrite: false
      })
    );
    g.add(line);
  });

  const cloud = pointsCloud(300, 4.5, 10.5, 0.22, sys.color, 0.40);
  g.add(cloud);

  if (sys.linkBatch !== false) graph.addSystemEdge(sys, halo);
  scene.add(g);
  sys.group = g;
  sys.halo = halo;
  systemCores.push(halo);
}

function makeNode(node) {
  const mat = new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color(node.color) },
      uHover: { value: 0 },
      uSelected: { value: 0 },
      uWarn: { value: node.status === 'warn' ? 1 : 0 },
      uFlash: { value: 0 },
      uFlashColor: { value: new THREE.Color(0x5eead4) },
      uTime: { value: 0 },
      uScale: { value: node.baseSize }
    },
    vertexShader: NODE_VS,
    fragmentShader: NODE_FS,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
  mesh.position.copy(node.pos);
  mesh.frustumCulled = false;
  mesh.userData.pick = node;
  node.mesh = mesh;
  scene.add(mesh);
  nodeMeshes.push(mesh);
}

function addLabel(kind, text, sub, color, pos) {
  const el = document.createElement('div');
  el.className = 'label ' + kind;
  el.innerHTML = '<span class="dot" style="background:' + color + '"></span>' +
    '<span class="txt">' + esc(text) + '</span>' +
    (sub ? '<span class="sub">' + esc(sub) + '</span>' : '');
  const obj = new CSS2DObject(el);
  obj.position.copy(pos);
  scene.add(obj);
  labels.push({ obj, el, kind });
  return obj;
}

function makeLabels() {
  coreLabel = addLabel('core', '星核 ' + model.passCount + '/' + model.shotCount,
    model.overall, '#5eead4', new THREE.Vector3(0, 3.4, 0));

  model.systems.forEach((sys) => {
    sys.labelObj = addLabel('sys', sys.label, sys.sub,
      '#' + new THREE.Color(sys.color).getHexString(), sys.center.clone().add(new THREE.Vector3(0, 2.3, 0)));
    sys.nodes.forEach((n) => {
      n.labelObj = addLabel('node', n.label, n.sub,
        '#' + new THREE.Color(n.color).getHexString(), n.pos.clone().add(new THREE.Vector3(0, 0.62, 0)));
    });
  });
}

/* ---------------- edges / pulses ---------------- */

const graph = {
  curves: [],
  addSystemEdge(sys, halo) {
    const a = new THREE.Vector3(0, 0, 0);
    const b = sys.center.clone();
    const mid = a.clone().add(b).multiplyScalar(0.5);
    mid.y += 3.2 + sys.center.y * 0.15;
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(64)),
      new THREE.LineBasicMaterial({ color: 0x3d5c74, transparent: true, opacity: 0.66, depthWrite: false })
    );
    scene.add(line);
    this.curves.push(curve);

    const pulse = new THREE.Sprite(new THREE.SpriteMaterial({
      map: TEX_GLOW, color: sys.color, transparent: true, opacity: 0.9,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    pulse.scale.setScalar(0.72);
    scene.add(pulse);
    pulses.push({ curve, sprite: pulse, offset: Math.random() * 0.8, speed: 0.035 + Math.random() * 0.02 });
  },
  addNodeEdges(sys, node) {
    const a = sys.center.clone();
    const b = node.pos.clone();
    const mid = a.clone().add(b).multiplyScalar(0.5);
    mid.y += 0.7;
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(24)),
      new THREE.LineBasicMaterial({ color: sys.color, transparent: true, opacity: 0.16, depthWrite: false })
    );
    scene.add(line);
  },
};

/* ---------------- camera / interaction ---------------- */

function noteInteraction() {
  controls.autoRotate = false;
  clearTimeout(idleTimer);
  if (!cruise) return;
  idleTimer = setTimeout(() => {
    if (!tween && !selected) controls.autoRotate = true;
  }, 12000);
}

function flyTo(pos, target, ms = 900) {
  clearTimeout(idleTimer);
  controls.autoRotate = false;
  controls.enabled = false;
  tween = {
    p0: camera.position.clone(),
    p1: pos.clone(),
    t0: controls.target.clone(),
    t1: target.clone(),
    start: performance.now(),
    ms
  };
}

function focusNode(node) {
  const dist = 10.5;
  const dir = camera.position.clone().sub(node.pos);
  if (dir.lengthSq() < 0.01) dir.set(0, 0.4, 1);
  dir.y = Math.max(dir.y, 0.22);
  dir.normalize();
  flyTo(node.pos.clone().add(dir.multiplyScalar(dist)), node.pos.clone(), 900);
}

function focusSystem(sys) {
  const dir = camera.position.clone().sub(sys.center);
  if (dir.lengthSq() < 0.01) dir.set(0, 0.5, 1);
  dir.y = Math.max(dir.y, 0.35);
  dir.normalize();
  const dist = sys.nodes.length > 16 ? 20 : 25;
  flyTo(sys.center.clone().add(dir.multiplyScalar(dist)), sys.center.clone(), 1000);
}

function homePos() {
  const f = camera.aspect < 0.7 ? 2.4 : (camera.aspect < 1 ? 1.35 : 1);
  return HOME_POS.clone().sub(HOME_TARGET).multiplyScalar(f).add(HOME_TARGET);
}

function overview() {
  select(null);
  flyTo(homePos(), HOME_TARGET, 1100);
}

function clearSelectionVisuals() {
  nodeMeshes.forEach((m) => { m.material.uniforms.uSelected.value = 0; });
  labels.forEach((l) => l.el.classList.remove('sel'));
  systemCores.forEach((s) => { s.material.opacity = 0.8; });
  if (coreSprite) coreSprite.material.opacity = 0.9;
}

function select(target) {
  selected = target;
  clearSelectionVisuals();
  const isStoryboard = !!(target && (target.shot || target.anchor));
  if (window.__fanxingMap && window.__fanxingMap.onSelect) {
    // 镜头/锚点交给分镜卡；其它目标关掉分镜卡，继续走质检面板。
    window.__fanxingMap.onSelect(isStoryboard ? target : null);
  }
  if (isStoryboard) {
    inspector.style.display = 'none';
    return;
  }
  inspector.style.display = '';
  if (!target) { showInspector(null); return; }
  if (target.kind === 'node') {
    target.mesh.material.uniforms.uSelected.value = 1;
    if (target.labelObj) target.labelObj.element.classList.add('sel');
  } else if (target.kind === 'system') {
    if (target.halo) target.halo.material.opacity = 1;
    if (target.labelObj) target.labelObj.element.classList.add('sel');
  } else if (target.kind === 'batch') {
    if (coreSprite) coreSprite.material.opacity = 1;
    if (coreLabel) coreLabel.element.classList.add('sel');
  }
  showInspector(target);
}

const raycaster = new THREE.Raycaster();
const ndc = new THREE.Vector2();

function pickAt(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(ndc, camera);
  const targets = nodeMeshes.concat(systemCores, coreSprite ? [coreSprite] : []);
  const hits = raycaster.intersectObjects(targets, false);
  for (const h of hits) {
    const p = h.object.userData.pick;
    if (p) return p;
  }
  return null;
}

function bindInteraction() {
  const canvas = renderer.domElement;
  let down = null;

  canvas.addEventListener('pointerdown', (e) => {
    down = { x: e.clientX, y: e.clientY };
    noteInteraction();
  });

  canvas.addEventListener('pointerup', (e) => {
    if (!down) return;
    const dx = e.clientX - down.x;
    const dy = e.clientY - down.y;
    down = null;
    if (dx * dx + dy * dy > 36) return;
    const hit = pickAt(e.clientX, e.clientY);
    if (hit) select(hit);
    else select(null);
  });

  canvas.addEventListener('dblclick', (e) => {
    const hit = pickAt(e.clientX, e.clientY);
    if (!hit) return;
    if (hit.kind === 'node') { select(hit); focusNode(hit); }
    else if (hit.kind === 'system') { select(hit); focusSystem(hit); }
    else if (hit.kind === 'batch') { select(hit); overview(); }
  });

  canvas.addEventListener('pointermove', (e) => {
    const hit = pickAt(e.clientX, e.clientY);
    if (hit !== hovered) {
      hovered = hit;
      canvas.style.cursor = hit ? 'pointer' : 'grab';
      nodeMeshes.forEach((m) => { m.material.uniforms.uHover.value = (hit && hit.kind === 'node' && hit.mesh === m) ? 1 : 0; });
    }
  });

  canvas.addEventListener('pointerleave', () => {
    hovered = null;
    nodeMeshes.forEach((m) => { m.material.uniforms.uHover.value = 0; });
  });

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') overview();
  });

  document.getElementById('reset').addEventListener('click', overview);
  document.getElementById('cruise').addEventListener('click', (e) => {
    cruise = !cruise;
    const btn = e.currentTarget;
    btn.classList.toggle('active', cruise);
    controls.autoRotate = cruise && !selected;
    if (!cruise) clearTimeout(idleTimer);
  });
}

/* ---------------- inspector ---------------- */

function chip(text, kind) {
  return '<span class="chip ' + (kind || '') + '">' + esc(text) + '</span>';
}

function showInspector(target) {
  inspector.style.display = '';
  if (!target) {
    inspector.innerHTML =
      '<div class="ins-kicker">批次星核</div>' +
      '<div class="ins-title">' + esc(model.passCount + '/' + model.shotCount) + '</div>' +
      '<div class="ins-chips">' + chip(model.overall, model.overall === 'PASS' ? 'ok' : 'bad') +
      chip(model.systems.length + ' 星系') + chip((model.legs.length + model.shots.length + model.slots.length + model.evidence.length + (model.workflowStages || 0) + (model.agentCount || 0) + (model.kbCount || 0)) + ' 节点') + '</div>' +
      [['功能族', model.systems.map((s) => s.label).join(' / ')],
       ['镜头', model.passCount + ' PASS / ' + (model.shotCount - model.passCount) + ' BLOCK'],
       ['信号', model.failures + ' 项']]
        .map((r) => '<div class="ins-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span></div>').join('') +
      '<div class="actions"><button class="btn" data-act="overview">总览</button><a class="btn" href="/">打开看板</a></div>' +
      '<div class="ins-note">拖动旋转，滚轮从星图拉近到单个节点。每个星系是一个功能族，每个光点是一个节点。</div>';
  } else if (target.kind === 'system') {
    const nodes = target.nodes || [];
    const pass = nodes.filter((n) => n.status === 'pass' || n.status === 'ok').length;
    inspector.innerHTML =
      '<div class="ins-kicker">SYSTEM · FUNCTION FAMILY</div>' +
      '<div class="ins-title">' + esc(target.fullLabel || target.label) + '</div>' +
      '<div class="ins-chips">' + chip(target.sub, target.status === 'block' ? 'bad' : (target.status === 'warn' ? 'warn' : (target.status === 'muted' ? 'muted' : 'ok'))) + chip(nodes.length + ' 节点') + '</div>' +
      [['族', target.id], ['节点', nodes.length], ['健康', pass + ' / ' + nodes.length], ['连线', target.linkBatch === false ? '全局/入口，不连批次' : '批次内']]
        .map((r) => '<div class="ins-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span></div>').join('') +
      '<div class="actions"><button class="btn" data-act="focus-system">聚焦星系</button><button class="btn" data-act="overview">总览</button><a class="btn" href="/">打开看板</a></div>';
  } else if (target.kind === 'batch') {
    showInspector(null);
    return;
  } else {
    const rows = target.rows || [];
    inspector.innerHTML =
      '<div class="ins-kicker">' + (target.workbench ? 'SHOT NODE' : 'NODE') + '</div>' +
      '<div class="ins-title">' + esc(target.label) + '</div>' +
      '<div class="ins-chips">' + chip(target.sub, target.status === 'block' ? 'bad' : (target.status === 'warn' ? 'warn' : (target.status === 'muted' ? 'muted' : 'ok'))) +
      chip(target.sys ? target.sys.label : '') + '</div>' +
      rows.map((r) => '<div class="ins-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span></div>').join('') +
      '<div class="actions"><button class="btn" data-act="focus-node">聚焦</button>' +
      (target.workbench ? '<a class="btn primary" href="/?sid=' + encodeURIComponent(target.id) + '">打开工作台</a>' : '<a class="btn" href="/">打开看板</a>') +
      '<button class="btn" data-act="overview">总览</button></div>' +
      '<div class="ins-note">双击节点可直接飞近；Esc 回到总览。</div>';
  }

  inspector.classList.toggle('empty', !target);
  inspector.querySelectorAll('[data-act]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const act = btn.getAttribute('data-act');
      if (act === 'overview') overview();
      else if (act === 'focus-node' && selected && selected.kind === 'node') focusNode(selected);
      else if (act === 'focus-system' && selected && selected.kind === 'system') focusSystem(selected);
    });
  });
}

/* ---------------- lod / loop ---------------- */

let lastTelemetry = 0;
function updateTelemetry() {
  const el = document.getElementById('telemetry');
  if (!el) return;
  const now = performance.now();
  if (now - lastTelemetry < 220) return;
  lastTelemetry = now;
  const d = camera.position.distanceTo(controls.target);
  el.textContent = 'VIEW ' + d.toFixed(1) + 'u · ' + model.systems.length + ' SYSTEMS · ' + (model.legs.length + model.shots.length + model.slots.length + model.evidence.length + (model.workflowStages || 0) + (model.agentCount || 0) + (model.kbCount || 0)) + ' NODES · ' + (model.agentCount || 0) + ' AGENTS';
}

function setLabel(entry, f) {
  if (!entry) return;
  const el = entry.el || entry.element;
  if (!el) return;
  const v = clamp(f, 0, 1);
  el.style.opacity = v.toFixed(2);
  el.classList.toggle('hidden', v < 0.02);
}

function updateLOD() {
  const h = renderer.domElement.clientHeight || 1;
  const k = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / h;

  nodeMeshes.forEach((m) => {
    const n = m.userData.pick;
    const d = camera.position.distanceTo(n.pos);
    const near = clamp((44 - d) / 36, 0, 1);
    let px = 6.0 + 48 * near * (n.sizeMul || 1);
    if (selected === n) px += 8;
    px = clamp(px, 6.0, 68);
    m.material.uniforms.uScale.value = px * k * d;
    m.quaternion.copy(camera.quaternion);

    const sysDist = camera.position.distanceTo(n.sys.center);
    let f = 0;
    if (n.sys.nodes.length > 16) f = clamp((26 - d) / 7, 0, 1);
    else if (sysDist < 40) f = clamp((40 - sysDist) / 9, 0, 1);
    if (d > 34 && selected !== n && hovered !== n) f = 0;
    if (selected === n || hovered === n) f = 1;
    if (n.labelObj && n.labelObj.element) n.labelObj.element.classList.toggle('near', d < 14 || selected === n || hovered === n);
    if (n.labelObj) {
      const lift = (px * 0.5 + 9) * k * d;
      n.labelObj.position.set(n.pos.x, n.pos.y + lift, n.pos.z);
    }
    setLabel(n.labelObj, f);
  });

  updateTelemetry();

  model.systems.forEach((sys) => {
    const d = camera.position.distanceTo(sys.center);
    if (sys.halo) {
      const s = Math.min(3.0, 170 * k * d);
      sys.halo.scale.setScalar(s);
      if (sys.inner) sys.inner.scale.setScalar(s * 0.19);
      if (sys.coreRing) sys.coreRing.scale.setScalar(Math.max(0.22, s / 3.0));
    }
    if (sys.flare) sys.flare.scale.setScalar(Math.min(7.5, 230 * k * d));
    const focus = selected === sys || hovered === sys;
    (sys.arcs || []).forEach((a) => {
      a.mesh.material.opacity = a.base * (focus ? 2.6 : 1);
    });
    (sys.dustBands || []).forEach((b) => {
      b.obj.material.opacity = b.base * (focus ? 1.9 : 1);
    });
    let f = 1;
    if (d < 16) f = clamp((d - 9) / 7, 0, 1);
    if (selected === sys) f = 1;
    setLabel(sys.labelObj, f);
  });

  const coreDist = camera.position.length();
  if (coreSprite) {
    const cs = Math.min(5.6, 250 * k * coreDist);
    coreSprite.scale.setScalar(cs);
    if (coreInner) coreInner.scale.setScalar(cs * 0.2);
    if (coreFlare) coreFlare.scale.setScalar(Math.min(11, 380 * k * coreDist));
    if (coreRing) coreRing.scale.setScalar(Math.max(0.2, cs / 5.6));
    if (coreRing2) coreRing2.scale.setScalar(Math.max(0.2, cs / 5.6));
  }
  setLabel(coreLabel, coreDist > 18 ? 1 : clamp((coreDist - 10) / 8, 0, 1));
}

function stepTween(now) {
  const t = clamp((now - tween.start) / tween.ms, 0, 1);
  const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  camera.position.lerpVectors(tween.p0, tween.p1, e);
  controls.target.lerpVectors(tween.t0, tween.t1, e);
  if (t >= 1) {
    tween = null;
    controls.enabled = true;
    noteInteraction();
  }
}

function updateSky(t) {
  const dir = camera.position.clone().sub(controls.target).normalize();
  const yaw = Math.atan2(dir.x, dir.z);
  // atan2 在 ±π 处会跳变；连续展开，避免天空/星云整块“回到初始状态”。
  let d = yaw - skyYaw;
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  skyYaw += d;
  const pitch = Math.asin(clamp(dir.y, -1, 1));
  skyMat.uniforms.uTime.value = t;
  skyMat.uniforms.uCam.value.set(skyYaw * 0.55, pitch * 0.55);
}

function updatePulses(t) {
  pulses.forEach((p) => {
    const u = (t * p.speed + p.offset) % 1;
    const pt = p.curve.getPoint(u);
    p.sprite.position.copy(pt);
    p.sprite.material.opacity = 0.25 + 0.75 * Math.sin(Math.PI * u);
  });
}

function resize() {
  if (!renderer || !sky || !composer) return;
  // 右侧数据列是独立占位，渲染尺寸必须跟 #scene 走，不能再用整个 stage。
  const w = Math.max(2, sceneHost.clientWidth);
  const h = Math.max(2, sceneHost.clientHeight);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();

  const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
  renderer.setPixelRatio(dpr);
  renderer.setSize(w, h, false);
  if (composer.setPixelRatio) composer.setPixelRatio(dpr);
  composer.setSize(w, h);
  labelRenderer.setSize(w, h);

  const skyH = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  sky.scale.set(skyH * camera.aspect * 1.06, skyH * 1.06, 1);
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  skyMat.uniforms.uRes.value.copy(size);
}

/* ---------------- boot ---------------- */

async function boot() {
  try {
    initRenderer();
  } catch (err) {
    fatal.classList.add('on');
    fatalMsg.textContent = 'WebGL 初始化失败：' + err.message;
    loading.classList.add('gone');
    return;
  }

  try {
    const [data, workflow, kb] = await Promise.all([
      loadData(), loadWorkflow(), loadKb()
    ]);
    model = buildModel(data, workflow, kb);

    // 把可编辑的镜头星系合并进主星图：替换质检里的“镜头”星系，其余星系原样保留。
    let canvasPayload = null;
    let canvasProject = '';
    try {
      const proj = await resolveCanvasProject();
      if (proj) {
        const payload = await loadCanvas(proj);
        const sb = await import('/storyboard_model.js');
        const sbModel = sb.buildStoryboardModel(payload);
        const sbSys = sbModel.systems[0];
        sbSys.linkBatch = false;
        model.systems = [sbSys].concat(model.systems.filter((s) => s.id !== 'shots'));
        model.shots = sbModel.shots;
        model.anchors = sbModel.anchors;
        model.canvas = sbModel.canvas;
        model.edges = sbModel.edges;
        model.status = payload.status || {};
        model.shotCount = sbModel.shotCount;
        canvasPayload = payload;
        canvasProject = proj;
      }
    } catch (err) {
      console.warn('[fanxing] 画布数据未加载，仅显示质检星图', err);
    }
    // 统一按质量做一次引力排布（星系绕质心、节点按质量分环）。
    layoutSystems(model.systems);
    window.__FANXING_MAP_MODEL__ = model;

    makeSky();
    makeStars();
    makeBatchCore();
    model.systems.forEach((sys) => makeSystem(sys));
    model.systems.forEach((sys) => sys.nodes.forEach((n) => {
      makeNode(n);
      // 镜头星系由 storyboard.js 重排，画到系统中心的旧连线会变成残线，跳过。
      if (sys.id !== 'storyboard') graph.addNodeEdges(sys, n);
    }));
    makeLabels();

    const pillOk = !model.overall || model.overall === '?' || model.overall === 'PASS';
    document.getElementById('batch-pill').className = 'pill ' + (pillOk ? 'ok' : 'bad');
    document.getElementById('batch-pill').innerHTML = '<span class="dot"></span>' +
      esc(model.overall && model.overall !== '?'
        ? model.overall + ' · ' + model.passCount + '/' + model.shotCount
        : '画布 · ' + model.shotCount + ' 镜');
    document.getElementById('batch-meta').textContent =
      ((canvasProject || model.batchDir) || '').replace(/\\/g, '/').split('/').slice(-2).join('/') || '—';

    bindInteraction();
    resize();
    camera.position.copy(homePos());
    controls.update();
    showInspector(null);
    window.__mapBooted = true;
    window.__map = { camera, controls, model, nodeMeshes, select, focusNode, focusSystem, overview, scene, sky, skyMat, getSkyYaw: () => skyYaw };
    window.__fanxingMap = {
      THREE, scene, camera, renderer, controls, raycaster, graph, labels,
      nodeMeshes, systemCores, select, focusNode, focusSystem, flyTo,
      makeNode, addLabel, pickAt,
      // Task 11 的拖动/框选直接用这两个：拾取屏幕点、按目标走同一套 select 流程。
      setSelected(target) { select(target); },
      mode: 'single', project: canvasProject, hasCanvas: !!canvasPayload,
      onSelect: null,
      setOtherSystemsVisible(v) {
        model.systems.forEach((s) => {
          if (s.id === 'storyboard') return;
          if (s.group) s.group.visible = v;
          if (s.labelObj) s.labelObj.visible = v;
        });
        if (coreGroup) coreGroup.visible = v;
        if (coreLabel) coreLabel.visible = v;
      },
      frameHooks: [],
      onFrame(fn) { this.frameHooks.push(fn); }
    };

    // 面板可能比星图先启动；就绪后把当前镜头状态补回来。
    if (window.__fanxingLive && window.__fanxingLive.snapshot) {
      try { applyFlashSnapshot(window.__fanxingLive.snapshot()); } catch (_) { /* ignore */ }
    }

    requestAnimationFrame((now) => {
      loading.classList.add('gone');
      animate(now);
    });
  } catch (err) {
    fatal.classList.add('on');
    fatalMsg.innerHTML = '数据或场景初始化失败：<code>' + esc(err.message) + '</code>';
    loading.classList.add('gone');
    console.error(err);
  }
}

let lastFrame = 0;
function animate(now) {
  requestAnimationFrame(animate);
  if (!renderer) return;
  const t = now * 0.001;
  const dt = Math.min(0.06, Math.max(0, (now - lastFrame) / 1000));
  lastFrame = now;

  if (bandGroup) bandGroup.rotation.y += dt * 0.0035;
  if (dustGroup) dustGroup.rotation.y -= dt * 0.006;
  twinkleMats.forEach((m) => { m.uniforms.uTime.value = t; });

  if (tween) stepTween(now);
  controls.update(dt);
  updateLOD();
  updateSky(t);
  updatePulses(t);
  gradePass.uniforms.uTime.value = t;
  nodeMeshes.forEach((m) => { m.material.uniforms.uTime.value = t; });
  updateShotFlash(now);

  if (window.__fanxingMap && window.__fanxingMap.frameHooks) {
    window.__fanxingMap.frameHooks.forEach((fn) => fn(now));
  }

  composer.render();
  labelRenderer.render(scene, camera);
}

boot();
