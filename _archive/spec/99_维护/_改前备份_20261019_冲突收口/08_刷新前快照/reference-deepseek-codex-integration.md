---
name: reference-deepseek-codex-integration
description: DeepSeek 接入 Codex CLI 的配置方法、成本对比；**V4.1 Flash 已发布（2026-09-10），新模型 ID＝`deepseek-flash`，旧名 `deepseek-v4-flash` 临时路由到它（所以不改配置也已在用）**
metadata:
  type: reference
---

**DeepSeek + Codex 集成（2026-09-11）**

**安装**：
```bash
npm i -g @openai/codex
```

**配置 `~/.codex/config.toml`**：
```toml
model = "deepseek-v4-flash"
wire_api = "responses"
api_key = "sk-xxxxxxxxxxxxxxxx"
```

**配置 `~/.codex/models.json`**：
```json
{
  "models": [
    {
      "slug": "deepseek-v4-flash",
      "name": "DeepSeek V4 Flash",
      "context_window": 1000000,
      "max_output_tokens": 16384
    }
  ]
}
```

**API Key 获取**：platform.deepseek.com → API Keys → 创建

**成本对比**：
| 模型 | 输入价格 | 输出价格 | 上下文 |
|------|---------|---------|--------|
| DeepSeek V4-Flash | ¥1/百万 token | ¥2/百万 token | 1M |
| GPT-4o | ~$5/百万 token | ~$15/百万 token | 128K |
| GPT-5.5 | 更高 | 更高 | 200K |

**性能对比**：
- 编程任务速度：DeepSeek 40s vs GPT 107s（快 2.7 倍）
- 代码质量：GPT-5.5 复杂推理仍领先，DeepSeek 日常编码足够
- 成功率：DeepSeek ~95% 日常任务，GPT ~99%

**使用建议**：
- 日常编码/重构/批量处理 → DeepSeek V4-Flash（便宜快）
- 复杂算法/多步推理 → GPT-5.5（质量高）
- 混合使用：`codex --model deepseek-v4-flash "..."` 或 `codex --model gpt-5.5 "..."`

**⚠️ 版本更新：V4.1 Flash（2026-09-10 官方发布，2026-09-14 查证）**
- **新模型 ID ＝ `deepseek-flash`**；旧名 `deepseek-v4-flash` 与 `deepseek-v4-flash-vision-exp` **临时路由到 V4.1 Flash** → 配置里写旧名的人**不改也已经在用 4.1**（用户就是这种情况）。建议显式改成 `deepseek-flash`，因为"临时路由"会停。
- 新特性：**原生多模态（能看图）**、价格下调且**闲时 = 高峰价的一半**（2026-09-10 12:00 起）、552B MoE + 新 Causal-Encoder-Decoder 结构、KV cache 降到上代 1/4 HBM / 1/8 SSD。
- 来源：官方公告 `api-docs.deepseek.com/zh-cn/news/news260910/`。

**可选的更大价值**：引擎 `config.yaml` 的 `cloud` 通道目前 **401 挂着**（见 [[project-cloud-channel-401]]，换 key 归用户）——DeepSeek 是 OpenAI 兼容，把它配成引擎的一个 backend（`api_key_env: "AW_DEEPSEEK_API_KEY"`，与既有 `AW_CLOUD_API_KEY`/`AW_DASHSCOPE_API_KEY` 命名一致）既换更强模型又顺手修那个 401。**未做，等用户点头**。

**Why:** 用户需要成本效益高的编程助手，DeepSeek 成本只有 GPT 的 1/35，速度更快，适合高频使用。
**How to apply:** Codex 默认用 DeepSeek（现应显式写 `deepseek-flash`），复杂任务切 GPT-5.5。API Key 从 DeepSeek 平台获取。**环境变量约定**：用户若加 `AW_DEEPSEEK_API_KEY`，引擎与我都能按名读取（引擎既有机制 `api_key_env`）；注意 `setx` 设完后**当前运行的 Qoder 进程看不到，须重启 Qoder**。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- Codex CLI 配置 + 成本（¥1/百万 token、1M 上下文）
- **V4.1 Flash 已发布(2026-09-10)：新 ID＝`deepseek-flash`，旧名临时路由到它→不改配置也已在用
- 原生多模态+闲时半价**
- 可顺手修引擎 cloud 401
