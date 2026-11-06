---
name: feedback-third-party-skill-install
description: 装第三方 skill 包的标准流程：按完整规格装、一个自带脚本都不装、脚本读懂后自己重写、厂商加密层不解
metadata:
  type: feedback
---

装第三方 skill 包（网盘课程包、社区包）时按这套走：

1. **按完整规格装**：目录名 == frontmatter `name`；缺 `name`/`description` 的**补齐再装**，但要在交付里点名"这份 frontmatter 是我写的，不是厂商的"。
2. **它自带的脚本一个都不装**（`.py/.js/.sh/.bat/.ps1/.exe/.enc/.dll` 全拦，命中即整包不装）。装后逐包 walk 复核"代码残留 0"。
3. **脚本要读懂之后自己重写**：把厂商脚本抽到只读目录通读，再按包内规范文档写自己的等价实现，并跑可复跑的自测（判据写在代码里）。
4. **正文照装不改**——只补 frontmatter，不动厂商正文一个字（同 [[feedback-collaboration-style]] 的"不许顺手改他的作品正文"）。
5. **厂商的 `.enc`／混淆层：默认不碰，但决定权在他**。判据分两层——真 DRM／需要破解密钥的不做；
   而**解码路径就明写在随包脚本里、密钥是公开常量串**的那种（厂商自己标 *anti-casual-reading only*），
   属于"编码不是加密"，用户点头就可以解。09-30 实例：29 号 skill 正文不装，
   但按他「剧本也可以解出来填充我们的资料库」把 160 个 `.enc` 解成了明文文本库。
   **解的时候必须拿厂商自己留的校验字段对账**（`sha256_16`／`char_count`），
   并入库时写清出处＋使用边界（只借机制、不复用对白桥段、不外发不整段转载）。
6. 装第三方包前先做**安全读法**：逐个查联网/子进程/env/凭证；报结论时点名是哪个脚本哪一行（同 [[feedback-server-security-reporting]]）。

**Why:** 用户 2026-09-30 明确指令「把缺失的补上，按完整规格装，但是不装它的脚本，脚本解析出来，自己写」＋「先审一遍再定」（针对带加密层的包）。第三方脚本不可控：实测 cybershot 那份把 API key 走 argv、model 写死成厂商自己账号的 endpoint，本来就不该直接跑。

**How to apply:** 下次他丢来一个 skill 包/课程包要装时用这套；不要 `cp -r` 了事，也不要"信厂商"直接跑它带的脚本。装完要新会话才在 skill 列表里出现（本轮实测：Qoder 桌面端当轮就热加载了，不必重启）。

### 10-01 实例：impeccable@bolder（社区技能，用户级已装）

- **官方市场在"角色/道具视觉设计"是空场**：463 个 design 类技能全是要做前端/UI；`concept art`、`角色设计` 两个词各 **0 命中**；MCP 只有 Figma/Webflow/Wix/Postman；插件是前端走查＋产品经理流程。**要找美术/造型设计能力，官方市场没有，只能去 skills.sh 或自建。**
- 装的是 `pbakaus/impeccable@bolder`（Apache 2.0，v4.4.0）。**自带脚本一个不装**：它带 `scripts/impeccable(.cmd)`（首次运行会自己下载二进制）、`live-browser*.js`、`modern-screenshot.umd.js`、`font-index.json` —— 全部剔除，只装 `SKILL.md` + `reference/`（43 文件／509K）。并把 frontmatter 里指向被删脚本的两条 `allowed-tools` 去掉。SKILL.md Setup 第 1 步（跑 launcher）因此必失败，**技能自带"Launcher unavailable"降级路径**（直接读 PRODUCT.md/DESIGN.md），所以正文仍可用。
- 🔴 **我递选项时漏标了它的真实范围**：这是一个**前端/UI 界面设计**技能，自述明写 "Not for backend-only or non-UI tasks"，`live/generate/hooks/init/document/extract` 对我们全无用。⇒ 以后给装机选项，**必须把"面向什么介质"写进选项描述里**，不能只写"专治太朴素"这种效果承诺。
- **真正可迁移的只有 `reference/bolder.md` 这套推理**，且它正好说出我的病灶：
  ① "reaching for more effects is the opposite of bold; reject it first" —— 加特效不是变大胆，**我做减法是同一种反射的相反方向**。
  ② "A flat section is one that quietly opts out of the system's own strongest moves" —— **剑就是那个退出的部件**：身上五片刻字肩甲＋裙摆同纹银绣，剑却是一根光条。
  ③ "Amplify what the system already owns… should look more like the same brand, not less" ⇒ **正解不是加光、不是加件数，是把已有的母题（护手／肩甲／裙摆那一行小字纹）用同一套语汇搬到剑上**。
  ④ "Commit, then clarify：make the one decisive move completely, then quiet everything around it" ⇒ **一个主角，其余降级**。
  ⑤ skeleton test：去掉材质，光看剪影还认不认得出这是谁的剑。
