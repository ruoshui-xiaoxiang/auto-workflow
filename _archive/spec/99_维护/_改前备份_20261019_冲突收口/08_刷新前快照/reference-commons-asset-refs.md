---
name: reference-commons-asset-refs
description: Wikimedia Commons 是取"单用途真物件参考图"（武器／道具／服饰设定级真照片）的正路，含 CC0  licensing 判法与 upload.wikimedia.org 必须带描述性 User-Agent 的坑；本机百度网盘库里没有物件设定图
metadata:
  type: reference
---

**用途**：当需要给生图模型挂**真物件参考图**（而不是我自己写样式形容词）时，来源＝Wikimedia Commons 的博物馆藏品照。10-01 实测取到的是英国王权剑（`File:Swords GIM Gold.jpg`，**CC0**，金十字护手四臂末端蓝珐琅金人物圆盘＋根部蓝珐琅内镶板），裁三张挂 i2i 多参考一次把"太朴素"治好。

**为什么走 Commons 而不是别的**：
- **许可干净**：`iiprop` 里带 `extmetadata.LicenseShortName`，直接筛 **CC0 / Public domain**——他要发抖音、可能商用，**不要 CC BY-SA**（10-01 那批里 `Flamberge Klingen…` 是 CC BY-SA 4.0、`Tvåhandssvärd…` 是 CC BY-SA 3.0，都被我排除）。
- **是"单用途真照片"**：整张图只有一个目标物件、中性背景、结构完整，正好落在他定的兜底顺序第二档（先回自己库挖同类原句 → **再拆单用途真照片** → 最后才让他找整图）。见 [[feedback-prompt-iteration-priors]]。

**三条硬坑（都踩过）**：
1. 🔴 **`upload.wikimedia.org` 不带描述性 User-Agent 时回一张约 2 KB 的 HTML 错误页**，扩展名还是 `.jpg`，不检查就会拿坏文件当参考。正解＝`curl -H "User-Agent: XxxBot/1.0 (用途; contact: …)"`；**判成功要验 `file --mime-type`，不能只看文件大小存在**。
2. **缩略图 URL 只能用 API 实际返回的那条**（`iiurlwidth` 给什么宽就有什么宽）；自己手拼 `/1600px-…` 会拿到 HTML。要原图就用 `imageinfo.url`。
3. **搜索语法要往简单写**：`srsearch=greatsword ornate crossguard filetype:bitmap` 回 **0 hits**（还提示"你是不是想搜 great wood"）；换成 `two-handed sword museum`／`sword of state gold`／`flamberge blade sword` 才出货。`srnamespace=6` 才是 File 命名空间。

**★本机库里没有物件设定图（10-01 查尽，别再重复查一遍）**：
- `E:\BaiduNetdiskDownload\中世纪欧洲人物\国王贵族骑士`（50 张三视图）——**全员空手**，剑只以"腰间挂佩剑搭环"这种一句话存在，画面里没有剑。
- `E:\BaiduNetdiskDownload\西方奇幻人物`（200 张）——提示词里 `剑` 字出现 **0 次**，同样明写"双手自然下垂并保持空手"。
- 全库 24 个顶层目录：`大剑／巨剑／双手剑／骑士剑` 命中 **0 份**，且**没有任何"武器／道具／兵器"目录**。
- 唯一现成的武器设定图＝`E:\创作\一剑霜寒\武器\巨剑\`（6 张 1536×1024），但**全是中式**（唐横刀、汉环首刀），其中一张还是发光冰晶剑＝"荧光棒"病灶本身。拼图留证在 `E:\创作\特效打斗练习件_20260930\生成层直出试验\sword_ref_real\_local_lib_greatsword.jpg`。
⇒ **要中式兵器**可以去那一档；**要西方骑士剑／王权剑／礼服剑**只能走 Commons。

**挂图前必做一步**：**把参考裁到只剩目标物件**。Commons 那张照片里有并排的第二把剑和一根金鞘，结果三批出图每条都有 1–3 张把鞘或第二把剑搬进画面，提示词里"别的剑、剑鞘不要进入画面"**没压住**。裁切比加禁令有效。见 [[reference-dreamina-canvas-cli]]。
