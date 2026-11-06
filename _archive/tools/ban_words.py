# -*- coding: utf-8 -*-
"""ban_words.py · 否定引导词表的**纯数据**真源（无 I/O、无 chdir、无项目依赖）。

为什么要把词表从 `prompt_lint.py` 里单拎出来（2026-10-19 治理批 Phase 4，全部数字为实测）
--------------------------------------------------------------------------------------
`check_preflight.py` 的 G7 需要这张否定词表来认「禁令句」。它原来靠 `import prompt_lint`
拿 `NEG`，而 `prompt_lint.py` 是**武昭君仪（wzy）项目**的脚本，不是通用底座：

  · `prompt_lint.py:18`  `D = r'D:/AIWorkflow/tmp/wzy'`（写死）
  · `prompt_lint.py:19`  `os.chdir(D)`  ← **import 时就改进程工作目录**
  · `prompt_lint.py:33`  `BASELINE = open(os.path.join(D, 'style_baseline.txt'))`  ← **import 时就读盘**
  · `prompt_lint.py:31`  `STYLE_PROFILE = os.environ.get('WZY_STYLE', ...)`  ← 变量名里就写着 WZY

实测证据（2026-10-19，从 `C:\\` 起进程）：

    cwd before import check_preflight : C:\\
    cwd AFTER  import check_preflight : D:\\AIWorkflow\\tmp\\wzy      ← 被悄悄搬走了

后果有两条，分开说：

  ① **任何 import 了 check_preflight 的进程，CWD 都变成了 tmp/wzy。** 之后所有相对路径
     都按 tmp/wzy 解析。这一条一直存在，只是没人写下来。
  ② **tmp/wzy 不在 ⇒ 词表静默降级。** `os.chdir` 与 `open(style_baseline.txt)` 都会抛，
     `_load_ban_words()` 捕获后返回 `(None, 原因)`，`check_preflight.py:551` 于是落到内置
     兜底镜像 `_BAN_MIRROR + _BAN_EN_MIRROR`。G7 只 warn 一句，闸还是绿的。

关于 ② 的**精确口径**（别把它说重了）：2026-10-19 实测两边**集合完全相同**——
    live(prompt_lint.NEG 过滤后) 37 条 ／ mirror 兜底 37 条 ／ `set` 相等 ／ 双向差集均为空。
唯一差别是**顺序**：index 27 处 `does not` vs `don't`。而消费点 `check_preflight.py:572`
是 `any(b in seg for b in BAN_LEADS)`——**纯成员判定，与顺序无关**。
⇒ **所以今天这个降级是"潜伏"不是"已发生"：判据不会变。**
   真正的风险是：将来有人给 `NEG` 补词而忘了同步 `_BAN_MIRROR`，那时才会静默漂。
   这份文件的存在就是为了让 `NEG` 不必再依赖 tmp 才能被读到。

本模块的纪律
------------
  · **只放数据。** 不许 import 项目模块、不许读文件、不许 chdir、不许看环境变量。
    这样它才能在依赖已经被搬走/删掉的情况下仍然可导入。
  · 下面 `NEG` 是 `prompt_lint.py:58-74` 的**逐字复制**（含全部标定注释——那些注释是
    09-28 / 10-03 三批人审的判据来历，不能悄悄毁掉）。
  · 🔴 **两份不能漂**：`tools/check_official_path.py [P9]` 会同时加载本模块与
    `tmp/wzy/prompt_lint.py`，逐个比对 `NEG`。集合不等就报 error。
    （`prompt_lint.py` 里那句"本表升为唯一词源"的承诺，现在由机器守着，不由记性守着。）
"""

# 出处：D:/AIWorkflow/tools/prompt_lint.py 第 58-74 行（与 D:/AIWorkflow/tmp/wzy/prompt_lint.py md5 全等 1cb65bab）
# 复制日期：2026-10-19。⚠ 改这里必须同时改 prompt_lint.py，否则 [P9] 会红。
SOURCE = "prompt_lint.py:58-74"
SOURCE_MD5_8 = "1cb65bab"

NEG = ['不要', '不许', '不可', '禁止', '没有', '去掉', '不出现', '不采用', '不添加', '一概不',
       '无需', '不描述', '看不见', '不露', '不画',
       # 09-28 补齐：这批是"否定副词＋能愿动词"的常用写法，旧表漏了它们——
       # 漏一个，那句"不得卡通化"就会被当成**肯定句点名**，把低危措辞报成高危（词表不闭合的代价）。
       # 全部 ≥2 字：裸「别」会把"情景别/景别"误判成禁令句（同"裸『无』撞无缝"那条教训）。
       '不得', '不准', '不应', '不宜', '切勿', '切莫', '严禁', '请勿', '绝不', '绝对不会',
       # 09-28 第二批补齐：`check_preflight.BAN_LEADS` 里有「切忌」而本表没有 ⇒ 同一句
       # "切忌三脚架入画"在**格式闸**算禁令句（低危）、在**词表闸**算肯定句点名（高危）。
       # 两张手写词表必然漂，故本表升为唯一词源：check_preflight 现在 import 本表。
       '切忌',
       # ── 10-03 批 16：英文否定引导词。这批**不是新加的判断**，是把 `check_preflight.BAN_LEADS_EN`
       #    已在用的那组搬进唯一词源（G7 认英文否定、词表闸不认 ⇒ 同一句 "do not show any tripod"
       #    在 G7 算禁令句、在词表闸算"肯定句点名"＝高危，正是 09-28 那条漂移的英文版）。
       #    带尾空格的条目（`no `／`not `／`never `）＝"后面紧跟一个词"的引导词形，
       #    由底座 `PF.term_pattern` 按子串语义处理，裸 `no` 不收（会撞进 nothing／notice）。
       'do not', 'does not', 'don\'t', 'never ', 'no ', 'not ', 'without', 'avoid',
       'with no', 'nor ', 'cannot']

# check_preflight 只用 ≥2 字的条目（裸「别」/裸 `no` 会误伤，见上面注释）。
# 在这里也导出一份过滤后的，免得调用方各写一遍过滤条件＝第二份口径。
NEG_USABLE = tuple(w for w in NEG if len(w) >= 2)

if __name__ == "__main__":
    import sys
    print("ban_words.NEG        : %d 条" % len(NEG))
    print("ban_words.NEG_USABLE : %d 条（≥2 字）" % len(NEG_USABLE))
    print("  中文 %d ／ 英文 %d" % (sum(1 for w in NEG_USABLE if not w.isascii()),
                                    sum(1 for w in NEG_USABLE if w.isascii())))
    print("出处：%s（md5 前 8 位 %s）" % (SOURCE, SOURCE_MD5_8))
    sys.exit(0)
