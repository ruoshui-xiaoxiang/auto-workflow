---
name: reference-public-memory
description: E:\公共记忆 跨工具共享记忆库（Trae/Qoder/Codex/管理软件统一读取）——写入规约：改 projects\*.md → bump 头部两行 → py build_index.py；index.json 勿手改
metadata:
  type: reference
---

用户维护**跨工具公共记忆库 `E:\公共记忆\`**：给 Trae / Qoder / Qoder CN / Codex / 管理软件统一读取的项目真实状态中心（README 定位：参考信息源，非强制纪律源；机密严禁入库，只写指针）。

写入规约（2026-09-07 实操验证通过）：
1. 事实源 = `projects\<project>.md`（ASCII 短横线文件名）；`index.json` 是 build_index.py 的派生投影，**勿手改**
2. 每个 .md 头部两行必须维护：`- 最新更新：YYYY-MM-DD HH:MM`（精确到分，只写日期会被拒）+ `- 摘要：一句话现状`
3. 流程：改正文 → bump 头部两行 → 跑 `py E:\公共记忆\build_index.py`（生成器拒绝未来时间/缺字段；正文 mtime 比声明晚 2 分钟以上会 WARN——连续编辑后需再 bump 一次并重跑）
4. 内容口径：只记结论/关键决定/影响范围/相关路径，不放大段日志；改动记录条目结构 = 日期标题 + 摘要/影响范围/相关文件/决策结论

现有条目：shuanghua-film-pipelines（影像管线，2026-09-07 已同步直出+超分+音轨结论）/ cuf-qs / local-ai / qoder / qs-monitor / auto-workflow / delivery-service / asian-face-lora / local-file-organization / **local-ai-workflow-rules（2026-09-28 新建：通道规则分治＋手册副本集＋统一备份验收，跨工具摘要；已登记进 `build_manual.py` → 手册 `08b_`，注意 08b 是逐条登记、非 glob，新文件不登记就进不了备份链）**。⚠ 已知遗留：`local-file-organization.md` 仍停在 2026-09-01，未记 09-28 全盘整理（待回填）；asian-face-lora、cuf-qs、delivery-service 有历史 mtime 漂移 WARN。

**How to apply:** 用户说「同步到（E盘）公共记忆」时：定位对应 `projects\*.md`（没有则复制 `_template.md` 改名），按上述规约更新并重建索引；与 Qoder 私有记忆可并存——私有侧记过程细节，公共侧记跨工具可见的状态结论。

---

## 2026-10-07 实地勘察（数字从盘上重读，非沿用上文）

库体量：43 文件 / 448 KB / 5 目录，**无 junction、无符号链接**（搬迁前按铁律查过）。结构＝`README.md`(10 KB)＋`build_index.py`(5.5 KB)＋`index.json`(11 KB)＋`projects\`(15 个 .md)＋`skills\`(25 个 .md)。

`projects\` 实有 14 条项目条目（比上文那份清单多 4 条）：`_template` `asian-face-lora` `auto-workflow` **`companion-desktop-pet`** `cuf-qs` `delivery-service` **`env-care`** `local-ai-workflow-rules` `local-ai` `local-file-organization` `qoder` `qs-monitor` `shuanghua-film-pipelines` **`wuyin`** **`wuzhaojunyi-h3-fight-pipeline`**(34 KB，最大)。`index.json` 的 `projects` 是 dict（键＝文件名去 .md），`library_root` 字段写死 `E:\公共记忆`。

**本机 agent 生态实测 9 个**（决定任何"按 agent 分区"的方案要建几个目录）：`.qoder` `.qoder-cn` `.trae` `.trae-cn`（**Trae 有国际版和 CN 版两套**）`.codex` **`.claude`（已安装，有 sessions/projects）** `.bailian` `.cursor` `.arkcli`；`.qianwen` 不存在。另有 E 盘数据目录 `E:\QoderCN_Data\.qoder-cn`。

🔴 **README 两处已过时**（改造时必须重做那张接入点表）：① 第 82 行写「Claude Code ⛔ 未安装、不要放 CLAUDE.md」——`C:\Users\若水\.claude\` 实际存在且有会话数据；② 接入点表完全没记 Cursor、bailian、arkcli、Trae 非 CN 版。

**引用面约 79 处**（grep `公共记忆`，仅文本扩展名）：`D:\AIWorkflow\tmp` 37（多为历史产物）、`E:\QoderCN_Data\.qoder-cn` 8、`.qoder\projects` 7、`.qoder\memory` 7、`.trae-cn\memory` 5、`.qoder-cn\memory` 5、`.qoder-cn\projects` 3、`.qoder\plans` 2，其余各 1。唯一**脚本级硬引用**＝`D:\AIWorkflow\tools\sync_skill.py` 第 30 行 `MIRROR = r"E:\公共记忆\skills\cinematic-video-production"`（改路径会直接跑挂）。`E:\公共记忆` 内部对自身路径的自引用 0 处。

## 改造需求与裁定（2026-10-07 提出，**暂缓**）

用户要的三件事：① 现库改造成「公共知识库」，库内按 agent 名字分区存项目记忆，**每个 agent 只能写自己那份、所有 agent 可通读**；② 旁边新建一个「公共记忆」，所有 agent 可读写；③ 现有公共记忆内容全部下沉到新公共记忆文件夹。

**裁定＝「那就先不急，等那边跑完」**——当时 Qoder CN 另一会话正在执行「全面优化本地工作流」，会碰 `AIWorkflow` 与 `.qoder-cn`，改名瞬间有撞车风险。命名/分流/时机三项他回 No preference，我按推荐锁定（旧库改名 `E:\公共知识库\` ＋ 新建同名 `E:\公共记忆\` 承接下沉，路径字面不变⇒引用零断裂；项目事实源下沉共享区、知识库只放各 agent 私有过程记忆；隔离走软约定＋hook＋attrib +R）。**开跑前需他一句话确认或推翻。**

🔴 **写隔离的技术天花板（别再重复论证）**：本机所有 agent 都以同一 Windows 用户「若水」身份运行，**NTFS ACL 按用户/组授权，分不清是哪个进程在写**⇒「只能写自己那份」在文件系统层做不到，除非给每个 agent 建独立 Windows 账户（要重配 E:\ 与 C:\ 全部路径访问权，不推荐）。可落地的强制力**必然不均匀**：Qoder 系 Hook 能硬拦（`PreToolUse` 退出码 2 阻断、stderr 回灌模型），Claude Code 也有 hooks；**Codex 只有 `AGENTS.md` 自觉层、无 hook**，Trae/Cursor 停在 rules 约定层。详见 [[reference-qoder-agent-skill-hooks]]。
