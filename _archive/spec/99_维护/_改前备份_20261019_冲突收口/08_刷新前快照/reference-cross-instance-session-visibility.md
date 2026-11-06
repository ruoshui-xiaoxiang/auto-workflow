---
name: reference-cross-instance-session-visibility
description: Qoder 与 Qoder CN 是互不可见的两个实例——MCP 会话工具读不到对方，只能旁路读盘上 qodercli 日志；含日志路径、可判读的信号与「导出件 vs 日志」的完整度差异
metadata:
  type: reference
---

用户会同时开 **Qoder（国际版）** 和 **Qoder CN** 两个客户端跑不同任务，并问我能不能看到另一个实例在干什么。2026-10-07 实测出完整边界，别再重新试一遍 MCP。

## 正规通道是断的

`mcp__builtin__list_chat_sessions` / `read_chat_session` / `wait_chat_sessions` / `send_message_to_chat_session` **只覆盖自己这个实例**。把 CN 的 sessionId 递给 `read_chat_session`，返回原话＝「这个会话未在 Qoder 中登记」；`list_chat_sessions` 也列不出它（`nextCursor` 为 null 即为列全）。

**Why**：两个客户端各有独立的会话注册表与 AppData——`com.qoder.app.stable` vs `com.qodercn.app.stable`（Roaming 下四个目录并存：`Qoder`、`QoderCN`、`com.qoder.app.stable`、`com.qodercn.app.stable`）。所以既不能 wait 跟踪，也不能 send 发指令。

## 旁路可读：盘上日志

路径＝`C:\Users\若水\AppData\Roaming\com.qodercn.app.stable\logs\<启动批次>\qodercli\sessions\<sessionId>.log`。启动批次目录名形如 `20261006-164300.876-27404-ccf3fc68`，**中间那段就是 PID**，可拿去和 `tasklist | grep -i "Qoder CN"` 对上，从而认出哪份日志属于当前活跃进程。

- 同一 sessionId 会跨多次启动各留一份；单份涨到 **20 MB 触发滚动切片**（`.log` / `.1.log` / `.2.log`）。
- 格式＝纯文本事件流，`YYYY-MM-DDTHH:MM:SS.mmmZ` 是 **UTC，本地 +8**。
- 能判读的信号：`session_message received type=` 分布（`stream_event` 海量、`assistant`/`user`/`system`/`result`/`command_lifecycle`）；**`type=result subtype=success` 就是一轮任务收尾**；按分钟统计事件数可判活/判卡（实测活跃态每分钟 600–900 事件）；`preview="..."` 字段带 user 消息与工具输出的**截断片段**，足以认出它在碰哪块代码。
- 判不到：完整对话正文、assistant 推理、工具名（grep `tool_name` 零命中）。
- ⚠ `preview` 片段里会夹带 ID 类字符串（见过 `oc_` 开头的会话标识）。按 [[feedback-credential-no-echo]] 不复述，但要提醒用户这类日志不干净。

## 导出件比日志完整得多

用户能从客户端导出会话为 Markdown（如 `若水影视公司_2026-10-07_02-03.md`，14.5 MB / 19 万行）。实测结构：头部有 `**Exported:**` 与 `**Work Directory:**`；正文按 `### **You**` / `### **Assistant**` 分轮，工具调用是 `#### Tool: <名>` ＋ `**Input:**` 的完整 JSON ＋ `**Response:**`。

一份 132 You 轮 / 153 Assistant 轮的导出件实测：5412 次工具调用（Bash 3612、Read 629、Edit 557、Write 520、mcp_call 32、Grep 20、AskUserQuestion 16…），**5410 个 Input JSON 完整**⇒等于所有被改文件的完整变更史；但 Response 只有 4917 个，**约 9% 的调用没有输出**。另有 90 处 `…` 截断。

🔴 **归因截断位置时我的尺子失准过**：用 awk 按最近的分节标记划区，90 处全归到 Tool 区块、正文 0 处——但抽查发现其中若干行明显是助手的论证正文，因为**导出件在工具块之后续写正文时不重打 `### **Assistant**` 标记**。所以不能据此断言"正文完整、只有工具输出被截断"。参见 [[feedback-evidence-loop-trap]]。

另注：正文里出现的 `truncated` 字样多是会话自己在讨论截断（Python unicodeescape 报错等），**不是导出标记**，别误当缺口。

## 接管评估的三条通用结论

1. **会话不持有产物**。实测那个 CN 会话的 cwd（`Documents\Qoder\2026-10-04\57871bfb`）是空的（`total 0`）；523 个被 Write/Edit 碰过的文件全在盘上（`D:\AIWorkflow` 452、`E:\QoderCN_Data\.qoder-cn` 29、`C:\Users\若水` 20、`E:\创作` 8）。⇒ 接管第一步是**读盘不读会话**。
2. **导出件是快照，会过期**。导出时刻之后 CN 仍在跑（眼看着日志继续长），中断后必须**重新导出一次**，否则缺增量。
3. 大导出件（14.5 MB）装不进上下文，只能当**可检索档案**按需 grep，不存在"读完再接手"。CN 侧若 0 次 TaskCreate，则没有任务清单可继承，多步指令的状态得从正文重建。

**How to apply**：用户问"能不能看到另一个实例"⇒ 直接答"MCP 不行、盘上日志可以"，并给出 PID 对号方法；问"能不能无损接管"⇒ 按上面三条给结论，明确区分**现场无损／变更史无损／叙述与增量有损**，并说明"中途不用我审核"那类授权是给那一轮那个 agent 的，我不自动继承（[[feedback-collaboration-style]] 元规则 M1）。
