# -*- coding: utf-8 -*-
r"""生成《官方英文词表 · 中文对照（人审版）》（10-03 批 14，用户要「官方英文词表翻译一份中文版作为人审版」）。

三条硬纪律（都是这一路踩出来的）：
1. **值一个都不抄**：所有英文原形、官方释义、条数都从 `check_official_contract.official()` 现读官方三模板，
   那个函数每次运行都重读盘上的 `prompts\official_h3\`（同一把尺，不再抄第二份解析式）。
2. **只补中文，不改官方**：本脚本里唯一的"内容"是中文译法表；官方哪天加了新词，
   这里会当场报「译法待补」并以退出码 1 停下——不会静默漏一行（假阴比假阳坏）。
3. 文件头写清「派生件·只重生成不手改」，改判据要改官方转写处（方案 §十三），不是改这份对照表。

用法：
    python build_official_lexicon_cn.py            # 生成／刷新
    python build_official_lexicon_cn.py --check    # 只核对：官方词是否都有译法、文件是否与生成结果一致
"""
import datetime
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BS = chr(92)                      # 反斜杠一律走这里：中文字符串里直接写 \b \h 会被转义咬掉
sys.path.insert(0, HERE)
import check_official_contract as COC          # noqa: E402

OUT = r"E:\本地工作流规范手册\00_读我\官方英文词表_中文对照_人审版.md"
# 用户 10-03 要「作为人审版放到桌面」⇒ 同一把生成器**同时**写桌面那份；
# 两份都由本脚本重生成、不许手改，所以不是第二份真源（真源＝官方三模板＋方案 §十三）。
DESKTOP = os.path.join(os.path.expanduser(u"~"), "Desktop",
                       u"官方英文词表_中文对照_人审版.md")

# ── 中文译法表（键＝官方原形，逐字取自官方；值是**我们的中译**，不是官方译文）────
GLOSS_MOT = {
    "Zoom In / Zoom Out": ("变焦推近／拉远", "焦距变、**机身不动**——画面像被"
                           "「拉近」，透视不变；与 Push 不可混用"),
    "Push In / Pull Out": ("机身前推／后退", "相机**实体前后移**——透视与空间感会变，"
                           "这是最常用的一种「推进」"),
    "Pan Left / Pan Right": ("左右摇镜", "机身不动、**镜头水平转向**（扫场／环视感）"),
    "Truck Left / Truck Right": ("左右横移", "整台相机**水平平移**（跟拍走位、揭示空间）"),
    "Tilt Up / Tilt Down": ("上下摇镜", "机身不动、**镜头垂直俯仰**（从脚扫到头／抬头看塔）"),
    "Pedestal Up / Pedestal Down": ("整机升降", "整台相机**垂直升降**，不改俯仰——"
                                    "与 Tilt 的区别就是机位高度变了"),
    "Arc Shot": ("环绕镜头", "以主体为圆心**弧线绕行**（展示立体感／对峙关系）"),
    "Tracking Shot": ("跟移镜头", "相机**跟着移动的主体走**（追、并行、领路）"),
    "Static Shot": ("固定镜头", "机位与镜头**都不动**——写它是有意的静止，不是漏写"),
    "Shake Slightly / Shake Strongly": ("轻晃／强晃", "手持感震动；**冲击、地震、混乱**用强晃，"
                                         "呼吸感用轻晃"),
    "POV": ("第一人称视角", "以某个角色的**眼睛当镜头**"),
    "Roll Clockwise / Roll Counterclockwise": ("顺时针／逆时针滚转", "绕**镜头光轴**旋转（失衡、"
                                                "眩晕、坠落感）；官方只给顺／逆，没给「90°」这类幅度词"),
}
GLOSS_AMP = {
    "with small amplitude": ("小幅度", "构图变化范围小——**微调、克制**；官方明示中档可省略不写"),
    "with large amplitude": ("大幅度", "构图变化范围大——**明显的推近／横扫**；吃不住容量时优先降它"),
}
GLOSS_SPD = {
    "at slow speed": ("慢速", "节奏缓；官方明示**常速可省略不写**"),
    "at fast speed": ("快速", "节奏急；与 Shake Strongly 常搭"),
}
GLOSS_STYLE = {
    "Cinematic": ("电影感", "官方 token，**照抄这个词**别写「电影级大片炸裂」这类自吹词"),
    "live-action": ("真人实拍", "写实影像质感（相对动画）"),
    "2D-animated": ("2D 动画", "赛璐璐／平面动画"),
    "3D CG": ("3D CG", "三维渲染（本机项目主力 token，如「高精度 CG 半写实」）"),
    "watercolor": ("水彩", "手绘水彩质感"),
    "claymation": ("黏土定格", "黏土／定格动画"),
    "vintage film": ("老胶片", "颗粒、偏色、年代感"),
}
GLOSS_CUT = {
    "the camera cuts to": ("镜头切到", "普通切镜官方首选句"),
    "the shot cuts to": ("该镜切到", "同义，换主语时用"),
    "the shot transitions to": ("画面过渡到", "普通切镜"),
    "the shot changes to": ("画面变为", "普通切镜"),
    "the shot switches to": ("镜头换成", "普通切镜"),
}
GLOSS_TASK = {
    "keyframe completion": ("关键帧补全", "图当**首帧／末帧／关键帧／编辑后关键帧**等具体画面锚——"
                             "本机的 i2va／fl2va 就是这个"),
    "reference generation": ("参考生成", "素材只提供**角色／场景／风格／动作／运镜／分镜的指引**，"
                              "不当具体帧、也不是被改的那片。⚠ 只给运镜切镜节奏的参考视频属这一类"),
    "video editing": ("视频编辑", "直接改**那段源视频**；改图、或在静帧之间生成**不算**这一类"),
    "video continuation": ("视频续接", "从已有源视频**往后续／延伸／接回／过渡**"),
    "audio reuse": ("音频复用", "同一条音频信号**整体或部分复用**（要保原词原音）"),
    "audio reference": ("音频参考", "不复制信号，只参考**曲风／音色／台词歌词内容／音效质感／节拍／连贯性**"),
}
GLOSS_VIS = {
    "fully_preserved": ("完全保留", "被参考内容按声明的职责**整份保留**"),
    "partially_preserved": ("部分保留", "仍在用，但某些特征被改或只留一部分"),
    "attribute_transfer": ("属性转移", "把参考到的特征**移到另一个可识别的主体**上（如服装给了乙）"),
    "weak_reference": ("弱参考", "只保留**风格／类别／构图／氛围的大致相似**"),
}
GLOSS_AUD = {
    "fully_copy": ("整条复制", "源音频**整条**当目标片的最终音轨"),
    "partially_copy": ("部分复制", "只抄一段／某几层，或抄完再增删换声音"),
    "reference": ("参考", "不复制信号，只参考**音色／节奏／曲风／台词内容／音质质感**"),
    "weak_reference": ("弱参考", "只保留类别或氛围的大致相似"),
}
GLOSS_FL = {
    "I2VA": ("首帧模式", "首帧就是 0.00 秒那一格，**逐字第一行 + 空行**再写三字段"),
    "FL2VA": ("首尾帧模式", "两张图分别钉 0.00 秒与片尾 S.SS 秒；正文**不许重复描述两张静帧**，"
                             "只写把它们连起来的运动路径"),
    "L2VA": ("末帧模式", "图只钉**最后一刻**，先写一个合理的前置状态再逐步收敛到它"),
}
FIRST_LINE_CN = {
    "I2VA": "对目标视频而言，在 0.00 秒处，<Picture 1>（属于 [Shot 1]）被完整引用。",
    "FL2VA": "参考图与目标视频的对齐关系——Picture 1（属于 Shot 1）对齐到目标视频的 0.00 秒处；"
             "Picture 2（属于第 N 镜）对齐到 S.SS 秒处。",
    "L2VA": "参考图与目标视频的对齐关系——<Picture 1>（属于 [Shot N]）对齐到目标视频的 S.SS 秒处。",
}
EXTRA_LINES = [
    ("正文语言（官方硬性）", "Write all six rewrite sections in English. Preserve the original "
      "language only for dialogue and lyrics inside `<d>` and for text visibly present in the scene.",
     "六个重写段落一律用英文；保留原语言只有三处：`<d>` 内的台词／歌词、画面里真实可见的文字。",
     "10-03 批 14 已建闸（G7，二值判据不带阈值）：正文出现中日韩字符就拦。"
     "**云端中文十块／图片链／即梦不吃这条**（通道分治）"),
    ("台词载体", "says: <d>[English] I get off at the next station.</d>",
     "台词写进 `<d>[语言] 原句</d>`，身份与 delivery 写在标签外。",
     "「出乱码就换引号」的退路已删（10-03 批 13）；画内可见文字才用英文双引号"),
    ("画外音固定短语", "says in an off-screen voiceover … while his lips remain completely closed",
     "画外音要用这个短语，并紧随声明画内角色双唇完全闭合。", "不声明闭嘴就会对口型"),
    ("听不清的片段", "[unclear]", "复用参考音频时听不清的片段写 `[unclear]`，不许猜也不许改写。",
     "凑字数／猜词都是违规"),
    ("切点必须带来新信息", "A cut should introduce new information about the subject, space, state…",
     "一次切镜要带出新信息（主体／空间／状态）；只换距离或微角度应改用运镜而不是切镜。",
     "写反打前先问这一镜新给了什么"),
    ("幅度速度的取舍", "Add amplitude and speed only when they are meaningful; medium amplitude and normal speed …",
     "只在有意义时写幅度与速度；中档幅度与常速通常省略。",
     "旧「三件齐全」自 10-03 批 12 起降为补充档（只在明确要求时判）"),
]
SELF3_NOTE = [
    ("`Throughout: …`", "不变量收在正文末尾的 `Throughout:` 句",
     "〔本层自写·官方未规定〕官方三模板现读该词 **0 次**，它来自本机 12 份真源写法；可用但别写成官方要求"),
    ("运镜句写在正文末尾", "本机关节：运镜句放 `integrated_multimodal_description` 末尾",
     "〔本层自写·官方未规定〕官方四条示例写在 `[Shot 1]` **第二句**"),
    ("首句写画幅／秒数／一镜到底", "本机写法：首句声明竖屏 9:16、几秒、一镜到底",
     "〔本层自写·官方未规定〕官方没这条；官方的第一行是上面那三种对齐指令"),
]


def render(d):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = []
    L.append(u"# 官方英文词表 · 中文对照（人审版）")
    L.append(u"")
    L.append((u"**派生件——只重生成，不要手改**：`99_维护" + BS + "build_official_lexicon_cn.py` 每次现读 "
              u"`D:" + BS + "AIWorkflow" + BS + "ComfyUI_H3" + BS + "prompts" + BS + "official_h3" + BS + "`（base-en／ref-en／SKILL）抽出全部固定值表，"
              u"本文件只往上添**中文译法**。生成时刻 `%s`；权威转写在 "
              u"`D:" + BS + "AIWorkflow" + BS + "ComfyUI_H3" + BS + "H3提示词工程规则方案.md` §十三，判据在通用层 R2。") % now)
    L.append(u"")
    L.append(u"用法：左边英文那列是**官方原形，逐字照抄进提示词**；中文列只是给你读的，不要翻成中文写进稿子"
             u"（官方硬性要求重写段落用英文）。")
    L.append(u"")
    L.append(u"## 一、运镜（官方 §4.3，共 %d 行）" % len(d["mot_rows"]))
    L.append(u"")
    L.append(u"| 官方原形（照抄） | 官方原话释义 | 中文（人审用） | 注意点 |")
    L.append(u"|---|---|---|---|")
    for en, gloss in d["mot_rows"]:
        cn, note = GLOSS_MOT.get(en, (u"⚠ 译法待补", u""))
        L.append(u"| `%s` | %s | **%s** | %s |" % (en, gloss, cn, note))
    L.append(u"")
    L.append(u"⚠ **计数三说**（别当成三版词表）：官方 §4.3 是 %d 行；把同行双向拆开写是 13 项；"
             u"机器匹配表 `CAM_EN` 是 14 项（多的那项是同义词 `Orbital`＝`Arc`，宽进匹配表，不是又一份可写清单）。"
             % len(d["mot_rows"]))
    L.append(u"")
    L.append(u"## 二、幅度与速度（官方：只在有意义时加，中档与常速通常省略）")
    L.append(u"")
    L.append(u"| 官方原形 | 官方释义 | 中文 | 人审怎么用 |")
    L.append(u"|---|---|---|---|")
    for en, gloss in d["amp_rows"] + d["spd_rows"]:
        src = GLOSS_AMP if en in GLOSS_AMP else GLOSS_SPD
        cn, note = src.get(en, (u"⚠ 译法待补", u""))
        L.append(u"| `%s` | %s | **%s** | %s |" % (en, gloss, cn, note))
    L.append(u"")
    L.append(u"## 三、风格 token（官方 §4.1，共 %d 个；写在 `[Shot 1]` 之后第一句）" % len(d["styles"]))
    L.append(u"")
    L.append(u"| 官方原形 | 中文 | 说明 |")
    L.append(u"|---|---|---|")
    for s in d["styles"]:
        cn, note = GLOSS_STYLE.get(s, (u"⚠ 译法待补", u""))
        L.append(u"| `%s` | **%s** | %s |" % (s, cn, note))
    L.append(u"")
    L.append(u"## 四、切镜措辞白名单（官方只给 %d 条）" % len(d["cuts"]))
    L.append(u"")
    L.append(u"| 官方原形 | 中文 |")
    L.append(u"|---|---|")
    for c in d["cuts"]:
        cn = GLOSS_CUT.get(c, u"⚠ 译法待补")
        L.append(u"| `%s` | **%s** |" % (c, cn if isinstance(cn, str) else cn[0]))
    L.append(u"")
    L.append(u"白名单之外只有用户明确点名时才允许：cross-dissolve／fade／wipe。"
             u"官方另一句：**切点要带来新信息**，只改距离或微角度应写运镜而不是切镜。")
    L.append(u"")
    L.append(u"## 五、`summary` 任务类型（官方 %d 种，多关系用 ` + ` 连）" % len(d["task_rows"]))
    L.append(u"")
    L.append(u"| 官方原形 | 官方释义（截断） | 中文 | 什么时候用 |")
    L.append(u"|---|---|---|---|")
    for en, gloss in d["task_rows"]:
        cn, note = GLOSS_TASK.get(en, (u"⚠ 译法待补", u""))
        L.append(u"| `%s` | %s | **%s** | %s |" % (en, gloss[:70], cn, note))
    L.append(u"")
    L.append(u"## 六、`retention_analysis` 关系标记（官方两对固定值：%d＋%d）"
             % (len(d["vis_rows"]), len(d["aud_rows"])))
    L.append(u"")
    L.append(u"### 可见内容（`<Subject>`／`<Picture>`／`<Video>` 用）")
    L.append(u"")
    L.append(u"| 官方原形 | 官方释义 | 中文 |")
    L.append(u"|---|---|---|")
    for en, gloss in d["vis_rows"]:
        cn = GLOSS_VIS.get(en, (u"⚠ 译法待补",))[0]
        L.append(u"| `%s` | %s | **%s** |" % (en, gloss, cn))
    L.append(u"")
    L.append(u"### 音频（`<Audio>` 用）")
    L.append(u"")
    L.append(u"| 官方原形 | 官方释义 | 中文 |")
    L.append(u"|---|---|---|")
    for en, gloss in d["aud_rows"]:
        cn = GLOSS_AUD.get(en, (u"⚠ 译法待补",))[0]
        L.append(u"| `%s` | %s | **%s** |" % (en, gloss, cn))
    L.append(u"")
    L.append(u"⚠ `weak_reference` 在两对里**是同一个词、两条不同释义**（可见＝风格／类别／构图／氛围的"
             u"大致相似；音频＝类别或氛围的大致相似），别合成一条。")
    L.append(u"")
    L.append(u"## 七、最终提示词的**第一行**（官方 §2.1 按模式各给一句，逐字）")
    L.append(u"")
    L.append(u"| 模式 | 官方逐字第一行 | 中文 | 说明 |")
    L.append(u"|---|---|---|---|")
    L.append(u"| T2VA | *（无对齐指令，直接以三字段开头）* | 没有第一行指令 | "
             u"官方原话：`T2VA has no image-alignment instruction`")
    for mode, sentence in d["fl_rows"]:
        cn, note = GLOSS_FL.get(mode, (u"⚠ 译法待补", u""))
        L.append(u"| %s | `%s` | %s | %s |" % (mode, sentence, FIRST_LINE_CN.get(mode, u"⚠ 译法待补"), note))
    L.append(u"")
    L.append(u"⚠ 官方规定这句「**必须是最终提示词的第一行**，其后空一行再写核心字段」；"
             u"本机现役只实现了 **I2VA** 那一句并被 G7 锁成 error。"
             u"**撞名预警**：`comfy" + BS + "h3_i2v_fl2va_*.json` 名字里的 fl2va **不是**官方 FL2VA（首尾帧），"
             u"它实为首帧 I2VA 通道（注册表 `h3_local.naming_note` 已记）。")
    L.append(u"")
    L.append(u"## 八、其余官方硬性句（人审最容易漏的）")
    L.append(u"")
    L.append(u"| 项 | 官方原话 | 中文 | 本机现状 |")
    L.append(u"|---|---|---|---|")
    for name, en, cn, status in EXTRA_LINES:
        L.append(u"| %s | `%s` | %s | %s |" % (name, en[:150], cn, status))
    L.append(u"")
    L.append(u"## 九、挂在「官方」名下但官方其实没写的三条（人审时别当厂商承诺）")
    L.append(u"")
    L.append(u"| 本机写法 | 是什么 | 状态 |")
    L.append(u"|---|---|---|")
    for name, what, note in SELF3_NOTE:
        L.append(u"| %s | %s | %s |" % (name, what, note))
    L.append(u"")
    L.append(u"---")
    L.append(u"")
    L.append(u"核对口径（本脚本现读，不抄数）：运镜 %d 行｜幅度 %d｜速度 %d｜风格 %d｜切镜 %d｜"
             u"任务 %d｜关系标记 %d＋%d｜§2.1 第一行 %d 形（另 T2VA 无形）｜正文语言原话 %d 处。"
             % (len(d["mot"]), len(d["amp"]), len(d["spd"]), len(d["styles"]), len(d["cuts"]),
                len(d["tasks"]), len(d["vis"]), len(d["aud"]), len(d["fl"]), len(d["eng_body"])))
    L.append(u"官方 `Throughout` 出现次数：**%d**（≠0 时说明厂商改了契约，第九节要重判）。"
             % d["throughout"])
    return "\n".join(L) + "\n"


def _norm(text):
    """把「生成时刻」那一小段抹掉再比——时间戳每次跑都不同，其余**逐字**必须一致。

    ⚠ 这里踩过一次：原来用 `split(生成时刻)[0]` 只比前半段，结果在文件**尾部**手加一行
    测不出来＝假阴（假阴比假阳坏）。现在改成整篇比、只挖掉时间戳。
    """
    return re.sub(u"生成时刻 `[^`]*`", u"生成时刻 X", text)


def missing_glosses(d):
    """官方有、中文译法表没有 ⇒ 列出来（这就是「官方改版了」的哨兵，别静默出一张缺行的表）。"""
    miss = []
    for en, _ in d["mot_rows"]:
        if en not in GLOSS_MOT:
            miss.append("mot:" + en)
    for en, _ in d["amp_rows"] + d["spd_rows"]:
        if en not in GLOSS_AMP and en not in GLOSS_SPD:
            miss.append("ampspd:" + en)
    for s in d["styles"]:
        if s not in GLOSS_STYLE:
            miss.append("style:" + s)
    for c in d["cuts"]:
        if c not in GLOSS_CUT:
            miss.append("cut:" + c)
    for en, _ in d["task_rows"]:
        if en not in GLOSS_TASK:
            miss.append("task:" + en)
    for en, _ in d["vis_rows"]:
        if en not in GLOSS_VIS:
            miss.append("vis:" + en)
    for en, _ in d["aud_rows"]:
        if en not in GLOSS_AUD:
            miss.append("aud:" + en)
    for mode, _ in d["fl_rows"]:
        if mode not in GLOSS_FL or mode not in FIRST_LINE_CN:
            miss.append("firstline:" + mode)
    return miss


def main():
    d, err = COC.official()
    if err:
        print(u"!! 官方模板读不出：%s" % err)
        return 1
    miss = missing_glosses(d)
    if miss:
        print(u"!! 官方词表有 %d 项没有中文译法，先补齐再出表：%s" % (len(miss), u"、".join(miss[:8])))
        return 1
    text = render(d)
    outs = [OUT, DESKTOP]
    bad = []
    for pth in outs:
        if "--check" in sys.argv:
            if not os.path.isfile(pth):
                bad.append(u"不在盘上：%s" % pth)
                continue
            cur = io.open(pth, encoding="utf-8").read()
            if _norm(cur) != _norm(text):
                bad.append(u"与生成结果不一致（被手改过？）：%s" % pth)
        else:
            if not os.path.isdir(os.path.dirname(pth)):
                print(u"!! 目标目录不在盘上，跳过：%s" % os.path.dirname(pth))
                continue
            io.open(pth, "w", encoding="utf-8", newline="\n").write(text)
            print(u"已写：%s（%s 字节，%d 行）"
                  % (pth, format(os.path.getsize(pth), ","), text.count("\n")))
    if "--check" in sys.argv:
        if bad:
            for m in bad:
                print(u"!! " + m)
            return 1
        print(u"译法齐全｜官方固定值全覆盖｜两份副本都与生成结果一致")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
