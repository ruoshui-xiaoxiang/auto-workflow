---
name: feedback-destructive-edit-boundaries
description: 批量改写/删除文件内容前必须先打印将要删的行范围让用户（我自己核对）看见；嵌套字符串里写反斜杠路径会静默吃字符，用 chr(92) 或 Edit 工具而非多层转义
metadata:
  type: feedback
---

两处今天各栽了一次，都是"看起来是小事、实际毁内容"的形态。

**一、删/替换的行范围边界必须先显式打印，再执行。**
给 `build_manual.py` 的 `SCRIPTS` 列表插两条新登记时，我的清理脚本取"第一条含 `(TOOLS + r"` 的行"
当作坏块起点 —— 但那是**正常的 `check_preflight.py` 条目**，不是我插坏的行。结果连着删掉 54 行、
16 条正常登记（`h3_shots.py`／`prompt_format.py`／`verify_g7_dispatch.py`／`backup_now.py` …）。
更糟的是 `py_compile` 照样通过、`--check` 照样报"源缺失 0"——**语法绿不等于内容齐**。

- **Why:** 编译器和"缺失=0"类校验只证明剩下的东西自洽，不证明没被删掉的东西本来存在。
  删多了是**静默**的，永远不报错。
- **How to apply:** 任何"删一段/替换一块"的脚本，先把**将删的行号范围与首行内容打印出来**，
  看到不认识的内容就是边界取错了；能锚"结束行"就同时锚两行。事后必须逐条点名核对
  （今天靠 12 个关键字 in 检查发现缺哪些），不能只看编译通过。改结构性文件前先想
  `find` 有没有第二份副本可还原 —— 我查了 `E:\_统一备份`、`_改前备份_*`、全盘 `find`，
  都**没有** `build_manual.py` 的第二份，只能靠上下文里读过的原文重建，运气而已。

**二、反斜杠路径穿过一层字符串就会被吃掉字符。**
同一天三次：`"...\review_publish.py"` 里的 `\r` 变成回车 ⇒ 文件里成了 `eview_publish.py`；
`\f` 变成 form-feed ⇒ `eishu_send.py`；`\9`、`\A`、`\_` 之类触发 SyntaxWarning 但仍写进文件。
Python 的 SyntaxWarning 只提示一次、且我插入用的是嵌套 heredoc 字符串，等于**两层转义**。

- **Why:** 这些变形不报语法错，只把路径改错，表现为"文件找不到"，很容易被当成别的原因。
- **How to apply:** 在脚本里生成含 Windows 路径的代码时，**用 `chr(92)` 拼反斜杠**，
  或者干脆用 Edit/Write 工具直接落文件，不要"Python 字符串里再套一段 Python 源码"。
  写文件类工具（Write/Edit）优先于 heredoc —— 今天的三次变形全部来自 heredoc 内嵌代码。

相关：[[feedback-evidence-loop-trap]]（可复跑自证）、[[feedback-copy-not-move]]（删源前要逐份哈希对上）、
[[feedback-disk-organization-rules]]（引用扫描根含被搬物自身）。

**三、从远端批量取文件：不许 `shell=True` 拼路径，清理之后必须刷新清单（2026-10-04 中式色彩库那一跑）。**
写下载脚本时我用 `subprocess.run(..., shell=True)` 把**仓库返回的 path** 拼进命令串——被安全钩子点名：
远端文件名是不可信输入，`$( )`／反引号这类拼进去就是命令注入。同时那一跑还连续犯了清单类的三个错：
首轮没排除脚本类文件（`.js`/`.html`/图片），落盘后才手工清掉 35 个，**结果盘上文件数已经和刚写的 MANIFEST 不符**；
另有约 8 个文件 curl 偶发取失败被我算成成功前的噪声；以及把 `git clone` 当默认取法（全局 `insteadOf` 已把它打死）。

- **Why:** "下下来了"和"内容对、清单对"是三件事；清理动作会把清单变成假的，而清单一旦与盘不符，
  下一次就没人再信它（同 [[feedback-evidence-loop-trap]] ㉔"清单要与盘一致"）。
- **How to apply:** ① `subprocess` 一律**传参数组、`shell=False`**，远端来的 path 先净化
  （拒绝对路径／`..`／盘符／控制字符，拼完再校验仍在目标目录内）；② 取回后**按 git blob 算法现算 sha1 与 tree 里的
  blob sha 逐份对账**，对不上记失败——不拿"HTTP 200"当内容正确；③ 首轮就按扩展名排除可执行与网页/图片，
  排除条件**别用子串 `.js`（会连 `.json` 数据一起杀掉），用 `endswith`**；④ 任何清理/删除之后**必须重新生成清单**；
  ⑤ 偶发失败的下载要重试若干次再判，取不到就显式列出来，不静默少几份。


## 延伸四：批量替换文件内容必须先过「编码 + 语法」双闸（2026-10-11 自造事故被闸拦下）

给 CUF 改名时同步更新引用，我把一段 **GBK 字节写进了声明 `# -*- coding: utf-8 -*-` 的 .py**，
6 份 `CUF_Kernel_v64_Full.py` 当场 `py_compile` 失败；因为我在写盘后立刻编译校验、失败就从备份还原，
最终这 6 份与备份逐字节一致，事故没有留下痕迹。`.ps1` 同理：用 `[ScriptBlock]::Create(读入全文)` **只解析不执行**当语法闸，
拦下了 1 份（那文件本身早就坏了）。

- **Why:** 文件名替换看起来是"改字符串"，实际是**改源码**。目标文件的编码不由我决定；
  按"命中时的编码"选替换编码会串台（needle 在两种编码下都能匹配时，我选了错的那种）。
- **How to apply:**
  ① 批量改内容前先读该文件的编码声明/BOM，**统一按文件自身的编码解码→改→同编码回写**，别做字节级撞运气；
  ② 写盘后立刻跑语法闸：`.py` 用 `py_compile(doraise=True)`，`.ps1` 用 `[ScriptBlock]::Create`（只解析），`.json` 用 `json.loads`；
     不过闸就**当场从备份还原**，并记 PYFAIL/PS1FAIL；
  ③ 收尾核验要"逐字节比对备份"证明还原是真的，别只看退出码；
  ④ 语法闸会生成 `__pycache__`：只清"本轮、且在我编辑过的目录里、且今天新建"的，历史 pycache 一律不碰；
  ⑤ 同一条纪律反过来用在判据上：反解乱码名时**拿整串试**（gb18030 严格反解 7 个全成功），
     单字符试一次就下"不可逆"的结论会误判——我曾据此写"救不回来"。
- 关联：[[feedback-copy-not-move]] 延伸五（同卷 rename 优先）、延伸六（0 字节空壳不算副本）、[[reference-cuf-assets-and-vault]]。


## 延伸五：写配置文件＝改机器的输入，禁用 PowerShell 写 JSON（2026-10-17 MiMo 事故）

MiMo 侧一个 agent 用 `ConvertTo-Json | Set-Content -Encoding UTF8` 重写 `~/.config/mimocode/mimocode.jsonc` 加一条 MCP，
结果用户报"我配的自定义 API 都不见了"。盘上实测：**三条 provider 与全部 MCP 逐字节都在**，但文件头三个字节变成 `EF BB BF`（BOM），
MiMo 的 jsonc 解析器不吃 BOM，日志直接报「mimocode.jsonc 不是合法 JSON:第 1 行第 1 列附近(InvalidSymbol)」并**拒绝加载整份文件**——
一个 BOM 把三条 API 配置和四个 MCP 一起屏蔽了。同一次重写还把 `"千问"` 二次解码成 `"鍗冮棶"`（PS 5.1 `Get-Content` 默认按 GBK 读 UTF-8 再写回），
原字只能从同目录 `.bak` 还原。

- **Why:** 延伸四讲的是"改内容"，这条讲"改的是机器输入"：配置文件的**字节头**和正文一样是契约的一部分，
  而且失败方式是**静默屏蔽**而非报错——用户看到的是"东西没了"，不是"文件坏了"，很容易误判成数据被删并去做更危险的动作（重装/重置配置）。
  `ConvertTo-Json` 还会顺手把缩进重排、把注释（`.jsonc` 的存在理由）整批丢掉。
- **How to apply:**
  ① 写 `.json`／`.jsonc`／任何被严格解析器读的文件，一律 **UTF-8 无 BOM**，用 Write／Edit／node／python 落盘；
     **不要在 shell 里 `ConvertTo-Json | Set-Content`**（PS 7 才把 `-Encoding utf8` 改成无 BOM，本机默认还是 5.1 行为）。
     🔴 而且**读也不行**：实测对修好的无 BOM UTF-8 文件取 `provider.alibaba-cn.name`，node 读到 `U+5343 U+95EE`（千问），
     PS 5.1 `Get-Content` 读到 `U+9357 U+51AE U+68F6`——默认 ANSI/936 码页把正确文件也读错了。⇒ 这类文件**读写都绕开 PS 5.1**。
  ② 判"配置丢了"之前先 `head -c 3 <文件> | xxd` 找 `efbbbf`，再读消费方的日志找解析报错；
     把内容剥 BOM 后 `JSON.parse` 跑一次——**过了就说明没丢，是加载失败**（别急着往回写数据）。
     🔴 **自验用错尺子＝假绿**（本轮最该记的一条）：肇事 agent 用 `Get-Content -Raw | ConvertFrom-Json` 自检并宣告"配置 JSON 校验通过 ✅"，
     而同一份带 BOM 文件在消费方解析器里必失败——**一把尺通过、一把尺失败，结论相反**。
     ⇒ 验配置只能拿**真正读它的那个程序**验（本例＝重启消费方看日志），拿另一个解析器验等于没验。
     ⚠ 判编码结果**别信终端渲染**：PS 的中文输出经管道回 bash 会被 GBK↔UTF-8 再叠一层，能把乱码渲染成正常汉字（我这次差点把"千问"当成没坏的证据），一律看码位或十六进制。
  ③ 修配置只动必要字节，并按延伸四的三道闸来：目标串**计数断言＝1**、写前落带名备份、写后**语法闸＋结构断言**
     （provider／mcp 条目数、key 非空数一个都不能少），最后与备份做**忽略空白的逐行 diff**，语义变化行数要能逐条点名解释。
  ④ 匹配乱码**别心算码位**：我按 hex `E9 8D 97` 算成 U+9317，盘上实测是 **U+9357 U+51AE U+68F6**，第一次替换直接 0 命中。
     要拿现文件的 codepoint 打出来再写转义。
  ⑤ 顺带同族：`--prefix` 装进 Electron 应用目录（那次装 `open-websearch` 就装进 `E:\mimo\Xiaomi MiMo\node_modules`）＝把包放进
     会被自动更新整目录重建的地方，工具会**静默消失**；装 npm 真全局前缀，删重复副本前按逐文件 tree sha256 对账（见 [[feedback-copy-not-move]]）。
  ⑥ ⚠ **BOM 是三态，别一刀切、也别"统一口径"**：`.ps1`／`.psm1` **要带 BOM**（PS 5.1 读无 BOM 的 UTF-8 脚本会把中文读成 GBK，见 [[reference-local-workflow-manual]]
     手册 §七 首条），`.json`／`.jsonc`／任何被严格解析器吃的文件**绝不能带 BOM**。判据只看**消费方是谁**，不看"谁写这个文件"。
     病根实证：MiMo 自己项目记忆（`~/.local/share/mimocode/memory/projects/global/MEMORY.md`，10-12）写着「.ps1 建议 UTF-8 BOM（兼容万一回退到 5.1）」——
     对 `.ps1` 是对的，但正是"BOM＝好习惯"被顺手带进 jsonc 的来源。**同一条纪律在不同消费方上结论相反时，要落成两态，不是择一。**
- 关联：[[reference-mimo-config-and-encoding]]（本轮实测细节与 MiMo 盘上事实）、[[feedback-evidence-loop-trap]]（"文件在"≠"在生效"）。
