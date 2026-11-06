# agent出片引擎 model gateway

OpenAI-compatible base URL: `http://127.0.0.1:8080/v1`

Backends (do not collide with Ollama/LM):
- `8081` qwen3-14b
- `8082` agent tiers (gpt-oss-20b / qwen2.5-7b)

Start via `E:\LocalAI\LocalAI.bat` menu 1. 
Agents MUST use this entry — see `E:\LocalAI\AGENT_DEFAULT.md`.

Four channels: Ollama 11434 | LM Studio 1234 | agent出片引擎 8080 (backends 8081/8082-8084) | 出片后端 ComfyUI 8189
Deprecated facades (do not start): 8787 engine WebUI, 8790 UI — see `D:\AIWorkflow\官方路径.json`.
Human-facing entry is `E:\LocalAI\娱乐流.bat` (8189 + panel only, no extra port). Agents submit via `D:\AIWorkflow\engine\run.py`.

## 繁星入口（2026-11-02）

- 人类导航统一在繁星面板：`E:\繁星\00_启动台\launchpad.json`（5 个白名单：娱乐流、agent 出片引擎、素材库、规范手册、创作工作区）；看板 8777 的 `/map3d`、`/starfield`（8788）、`/launch`。这些是 UI/导航，不是模型网关，也不是新的 ComfyUI 端口。
- Agent 常规工作流走 `py -3.12 -m fanxing workflow ... --through gate`（默认停在跑前闸，`--execute-run` 才提交 8189）；直接 `h3_spider batch`/`h3_run_project.py` 只算调试/逃生门。
- 8080 仍是 LocalAI 模型网关；8189 仍是唯一 ComfyUI 实例；8777/8788 只是繁星看板。
