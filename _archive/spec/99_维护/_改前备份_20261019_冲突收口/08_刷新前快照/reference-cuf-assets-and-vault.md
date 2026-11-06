---
name: reference-cuf-assets-and-vault
description: CUF 项目的资产落点、跨盘备份与境外服务器私有 git vault 的现状（2026-10-11 全盘核实），以及 GitHub 直连的可用方法与两个待裁风险（默认密钥、手机号邮箱）
metadata:
  type: reference
---

# CUF 资产版图与备份通道（2026-10-11 全盘实测）

CUF = 用户自建框架（v1–v6 叫 Causal-Unity Framework，v7 叫 Causal Universe Framework），
署名「若水小湘」在公开 SCU3 README，不在 v7 正文里。实验载体是《赛博朋克 2077》具身工程 CUF-QS。

## 落点（都是实测，别按旧报告的数字想）

- **三份 CUF-QS 工程副本**：`E:\6a8b0dd1b3ead574d77ceda3`（18,255 文件，含 2→3 提交的 cuf-qs 仓、全盘唯一的 `logs\pc_hl`、547 MB 的 `logs\formal_batch_7b_v3`）｜`E:\QODERCN`（22,519 文件，含 QS Monitor 活源码）｜`E:\文档\CUF-QS`（2,309 文件，12 份 PDF/docx + 一处实验归档子树）。关键文档 sha256 互相相同，不是硬链接（全盘 CUF 树内重析点 0、`st_nlink` 全为 1）。
- `E:\归档区\CUF` 剥离后只剩 **171.6 MB / 1,604 文件**（原 18.14 GB / 66,304）。剥出去的两块：`E:\归档区\SCU8.0正式版_备份`（64,016 文件 / 6.2 GB，SCU 应用快照，与 `E:\归档区\SCU8云服务器一键部署包`、`SCU8云端部署脚本` 同线）和 `E:\_杂项\KuGou缓存_来自CUF归档`（684 文件 / 10.73 GB，纯 `.kgtemp/.krc`，可再生）。留痕 `E:\归档区\_CUF归档剥离记录_20261011.md`。
- **原报告完全漏掉的一条线**：`E:\文档\CUF专利\新建文件夹\` = CUF v3/v4.1 整条代码线（`cuf_main.py` 5 版、`cuf_pair_core.py` 4 版）+ 专利附图 JPG + `CUF_v4.1_Theory_Report.pdf`，31 MB。`CUF_Kernel_v64_Full.py` 的**最大版（129,559 B）在这里**，不是归档区那份 83.8 KB。
- `E:\QODERCN\ai_agent_monitor`（2.2 GB / 10,218 文件）是**正在对外发行的 QS Monitor 的活源码，无任何 git 覆盖**。
- 磁盘物理事实：`E:`＝Disk #0（SATA 1863 GB，剩 1.5 TB）；`C:`/`D:` 同在 Disk #1（NVMe，D 剩 93.7 GB）。**CUF 全部资产此前只在 Disk #0 上，且 `E:\BaiduSyncdisk` 里一个 CUF 文件都没有。**

## 备份与 vault 现状（本轮已建立）

- 跨盘备份：`D:\CUF_备份_20261011`（5,474 文件 / 1,010.7 MB，逐文件 sha256 双向对账 0 失配，`MANIFEST.csv` + `_README.md` 记名未纳入项）。
- 私有 git vault：服务器 `47.250.138.158`（他的产品站机，见 [[reference-user-website]]）`/root/git`（700）下三个 bare 仓 `cuf-qs.git` / `CUF-Agent-Platform.git` / `ai_agent_monitor_backup.git`；本地各加了一个名为 **`vault`** 的远端，**origin 一律未动**。推送后 `git ls-remote vault` 与本地 `rev-parse HEAD` 逐个相等。
- 用户裁的口径（原话「走境外服务器通道提交」）：CUF 的 git 备份落自己的境外机，不落 ghproxy 镜像，也不要 GitHub 私有仓。

## GitHub 直连：可用方法（本轮实测）

- 全局 git 有 `url.https://ghproxy.cn/https://github.com/.insteadOf=https://github.com/` + `http(s).proxy=127.0.0.1:7890`；Clash 没开时 git 远程操作全失败，且**四个 CUF 仓的 remote 已存成 ghproxy 改写后的地址**。ghproxy 对 git 的 `info/refs` 端点**不稳定**（同一命令一次通、三次「not valid: is this a git repository?」）。
- `-c url."https://github.com/".insteadOf=...` 这种**单命令反向覆盖无效**——两条规则链式互抵，ghproxy 地址绕回 github 又被全局规则改写回去。
- **有效解法**：隔离配置环境，`HOME=<空目录> GIT_CONFIG_NOSYSTEM=1 git ls-remote https://github.com/<owner>/<repo>.git`（实测拿得到 sha；curl 直取 `info/refs?service=git-upload-pack` 也回 200）。⇒ github.com 本身可达，卡的是他自己的全局配置。
- ssh 到 vault 必须显式带 `-o UserKnownHostsFile=<该机的 3 类 host key 齐全的文件>`：中文用户名下 Windows ssh 解析 `~/.ssh` 会走偏，光 `-o StrictHostKeyChecking=yes` 会报「No ED25519 host key is known」。参见 [[feedback-file-link-format]] 同源的环境坑。

## 两条待裁风险（已核实，未动）

- **默认密钥**：公开 SCU3 仓（MIT）里 `SCU3_dev_key_2026`/`SCU3_admin_key_2026` **32 处 / 7 文件**（server.py 162/164 是 `_DEV_DEFAULT_*`，另有 test_7b.py、verify_retrieval.py、web/index.html、BLUEPRINT_v3.1/index.html、SCU2_v5.0_最终交付文档.md 20 处、白皮书 v4.0 3 处）；归档区用的是**另一串** `scu2_*`（.md 里 120 处）。缓解：`SCU3_HOST` 默认 `127.0.0.1:8300`，用默认 key 启动打「默认Key已公开在源码中，不安全！」告警，监听 0.0.0.0 再告警；仓内无第三方真实 key。改写公开仓＝force push，归他裁。
- **PII**：全局 git 身份 = `l<手机号已脱敏>-boop / <邮箱已脱敏>@gmail.com`，该邮箱已发布在 SCU3 与 ai-agent-monitor 两个公开仓的提交历史（author+committer）。GitHub 隐私开关不改历史；`filter-repo` 重写有代价。这也解释了那个「第 6 个仓库」remote `l<手机号已脱敏>-boop/SCU3_staging`——是他自己旧账号，现已 404＝孤儿远端。

## 文本侧的三条硬更正（引用 v7 时别再写错）

- v7 声称「十七条可证伪锚点」，**附录 A 实列 11 条**（P_D1/P_D2/P_M1/P_W1/P_W2_1–6/P_C）；`H_L` 只在对照报告里。
- 正文没有 `C_H = struct + adapt + extend` 这个加法式，L255 明确写「单一成本在三个维度上的投影」。
- 「S27 v3 判定规则改成 `observed_diff>0 ∧ p≤0.05`」在对照报告 L152 有记载，但**报告没有明文承认它是看到 v1/v2 结果之后才改的**——这条属推断，别写成「他已披露」。

## 未纳入版本控制的证据（成因）

`E:\6a8b0dd1b3ead574d77ceda3\.gitignore` 第 24/25/39 行写着 `logs/formal_batch_7b_v3/`、`logs/pc_hl/`、`.trae/`。
⇒ v7 主文本与 pc_hl 日志**本来就被规则挡在 git 之外**，所以「无远端备份」不是偶然。本轮用 `git add -f` 把 pc_hl(186) 与 `.trae\cuf_v7_extract.txt` 入了库（ignore 规则未改，等他裁），547 MB 的 v3 原始数据继续留库外、由 D 盘备份承接。
另有 22 个 tracked 文件已从工作区删除（整个 `s1_backup\` 版本锁序列：CufBridge 0.4.0–0.6.16 init.lua、`version_lock.json`、CET/RedSocket/red4ext 配置），历史里还在，盘上没有。
