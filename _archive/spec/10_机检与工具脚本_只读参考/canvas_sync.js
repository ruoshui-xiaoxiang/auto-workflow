/* 繁星 → ComfyUI 画布同步（一次性粘贴到 ComfyUI 的 DevTools Console）
 *
 * 前置：
 *   1. 繁星 h3_run_project.py 每跑一镜会写
 *      ComfyUI/user/default/workflows/_fanxing_latest.json
 *   2. ComfyUI 页面保持打开（不需要重启服务）
 *
 * 行为：
 *   - 每 1.5s 检查最新同步文件；version 变了就 app.loadGraphData(...)
 *   - 画布会被替换为“当前镜头 + 当前项目资产 + 当前提示词”的图
 *   - 要停止：clearInterval(window.__fanxingCanvasSync)
 */
(async () => {
  if (window.__fanxingCanvasSync) clearInterval(window.__fanxingCanvasSync);
  let last = null;
  const URL = "/api/userdata/workflows%2F_fanxing_latest.json";

  async function tick() {
    try {
      const r = await fetch(URL + "?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) return;
      const d = await r.json();
      const v = d && d.fanxing_sync && d.fanxing_sync.version;
      if (!v || v === last) return;
      last = v;
      await app.loadGraphData(d.workflow, true, false);
      console.log("[fanxing] canvas sync", d.fanxing_sync);
    } catch (e) {
      console.warn("[fanxing] canvas sync failed", e);
    }
  }

  window.__fanxingCanvasSync = setInterval(tick, 1500);
  tick();
})();
