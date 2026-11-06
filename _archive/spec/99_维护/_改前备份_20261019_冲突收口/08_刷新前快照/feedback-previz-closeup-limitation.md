---
name: feedback-previz-closeup-limitation
description: 灰模 previz 只能验证机位/调度/节奏，特写镜给不了脸/神态/精细度——特写质检要另走角色静帧+锁脸
metadata:
  type: feedback
---

**灰模 previz 只管机位/调度/节奏，对特写镜没用**：灰模里无音是无脸的灰色胶囊人形、小Q只有蓝屏脸，给不了五官/神态/眼神/精细度。

**Why:** 用户原话「灰模精细度还是差了点，对于特写镜头没有用」——特写镜（05C 无音贴脸跟坠、05A 小Q逗蜥蜴）的信息核心就是脸和表情，灰模天生没有。

**How to apply:** 特写镜的质检/出片拆三层，别指望灰模解决精细度：
1. 灰模 → 定机位、构图、节奏（free、秒出）
2. Seedream 出该镜的角色特写静帧 → 定脸/神态/光罩/躺姿（¥0.3/张）
3. 拿这张静帧当 reference_image 上 Seedance r2v → 锁脸 + 灰模运动轨迹

卡住特写的往往是中间那张「角色特写静帧」没正经出过，或定妆参考图本身精细度不够（无音 char_e01 vs 阿音候选之争）。关联 [[feedback-character-reference-image]] [[feedback-previz-camera-rhythm]]。
