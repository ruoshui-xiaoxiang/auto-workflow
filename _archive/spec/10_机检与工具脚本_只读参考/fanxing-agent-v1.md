# 繁星系统 · Agent 共签协议 v1

版本：`fanxing-agent-v1`
日期：2026-11-01
适用：所有接入繁星系统的 agent。接入即表示接受本协议。

---

## 0. 一句话

**每个 agent 用不可变的 `agent_id` 接入；所有工作流都带这个 id；知识共享、记忆私有、产物可追溯；主序星只是入口的可视化，不是路由。**

---

## 1. 身份

| 字段 | 规则 |
|---|---|
| `agent_id` | 不可变，`^[a-z0-9][a-z0-9_-]{1,31}$`；改名不换 id |
| `name` | 显示名，可改 |
| `owner` | 负责人/归属 |
| `status` | `active / revoked` |
| `scopes` | 权限列表，见 §3 |

`agent_id` 一旦注册就不能复用给别的 agent。停用只改 `status`，不删除历史。

## 2. 共签

1. agent 阅读本协议；
2. 运行 `agent join --accept-contract`，本地生成 agent 记录；
3. 系统对记录做双重哈希签名：
   - `agent_signature = sha256("agent|" + canonical(record))`
   - `system_signature = sha256("system|" + contract_sha256 + "|" + agent_signature)`
4. 记录写入 `agents.json`；任意字段被改，签名校验失败，接入被拒。

这是**防篡改校验**，不是 PKI 身份认证；本地信任模型下够用。未来要跨机器分发，再升级成密钥对。

协议版本变化时，`contract_sha256` 变化，旧记录会被判 `contract_stale`，agent 必须重新 `join --accept-contract`。

## 3. 权限 scope

默认：

```
workflow:read, workflow:run,
knowledge:read,
memory:read:self, memory:write:self,
skill:read, agent:read
```

- `knowledge:*`：共享知识库；写入需 `source/version`，默认只读。
- `memory:*:self`：只能读写自己的记忆；跨 agent 读取必须显式授权。
- `workflow:run`：允许发起工作流；不等于允许提交 GPU，见 §5。
- 没有 scope 的请求一律拒绝，不做“默认放行”。

## 4. 数据规则

- 知识（knowledge）：可共享，必须有 `source`、`version`、`updated_at`；回答必须能引用来源。
- 记忆（memory）：默认 agent 私有，必须有 `valid_from`；冲突时新记录用 `supersedes` 覆盖旧记录，不静默改写历史。
- 技能（skill）：只登记 agent 实际在用的技能；能力边界写清楚，不把“没验证”写成“支持”。
- 工作流产物（workflow/artifact）：每次运行写 `workflow.json`，阶段、耗时、产物路径、闸门结果都可追溯。
- 禁止：编造条目、把别人的记忆复制进来、把未验证的结论写成知识、跨 scope 偷读。

## 5. 工作流接入

### 5.0 入口纪律

常规工作流必须走 `fanxing workflow`。直接调用 `h3_spider batch`、`h3_run_project.py` 只算调试/逃生门，不携带 agent 上下文，不算接入。

### 5.1 命令

```bash
cd D:/AIWorkflow/tools

# 首次接入（只做一次；协议更新后重做）
py -3.12 -m fanxing agent join \
  --id h3-spider --name "H3 蜘蛛" --owner 若水 --accept-contract

# 默认：预检 → 建稿 → 质检 → 跑前闸，停在出片前
py -3.12 -m fanxing workflow \
  --agent h3-spider \
  --project "C:/Users/若水/Movies/Hub/Projects/未命名项目/h3" \
  --out "C:/Temp/fanxing_runs/h3-spider_001" \
  --shots U01 U02 \
  --through gate

# 真正提交 GPU 必须显式加 --execute-run
py -3.12 -m fanxing workflow ... --through run --execute-run
```

### 5.2 阶段

| 阶段 | 产物 | 失败行为 |
|---|---|---|
| `precheck` | `precheck.json` | error → BLOCK，后续不跑 |
| `build` | 项目 `out/Uxx.txt` + `build_report.json` | 任一镜失败 → BLOCK |
| `qc` | `qc/batch_verdict.json` | 批跑 BLOCK → BLOCK |
| `gate` | `gate.json` | 拒跑 → BLOCK |
| `run` | `run/` 下视频 | 默认跳过；只有 `--through run --execute-run` 才提交 |

`--through` 决定跑到哪一步；后面的阶段标记 `skipped`，不算失败，但也不会伪装成通过。

### 5.3 退出码

- `0`：已完成阶段全部 PASS
- `1`：BLOCK（预检/建稿/质检/闸门/出片失败）
- `2`：用法/身份/协议错误（agent 未注册、协议过期、scope 不足）

## 6. 星图入口（主序星）

- 每颗主序星 = 一个 `active` agent 的入口；星图只读，不承担路由。
- 只有 registry 里有真实记录、且该 agent 有工作流/知识/记忆数据时才显示星；没有数据不造星。
- 点击星只切换该 agent 的 scope/filter；真正的调用仍走 CLI/HTTP，带 `agent_id`。
- 星的颜色/大小来自真实状态与数据量，不做装饰性假数据。
- agent 改名不换星，只换标签；停用后星进入归档态，不删除历史。

## 7. 边界

- 本系统负责编译期结构/契约质检，不对模型生成漂移负责。
- `--execute-run` 是显式付费/占 GPU 动作；默认不触发。
- 本地信任模型；跨机器/多用户前，需要补密钥对、传输加密和审计。
- 协议未定义的字段不要自造；先提协议变更，再改实现。

## 8. 接入检查单

- [ ] 读过本协议，接受 `fanxing-agent-v1`
- [ ] `agent_id` 已确定且不再改
- [ ] `agent join --accept-contract` 成功，签名校验通过
- [ ] 用 `--through gate` 跑通一次，`workflow.json` 可读
- [ ] 需要 GPU 时才使用 `--through run --execute-run`
- [ ] 失败时保留 `workflow.json` 与阶段日志，不静默重试
