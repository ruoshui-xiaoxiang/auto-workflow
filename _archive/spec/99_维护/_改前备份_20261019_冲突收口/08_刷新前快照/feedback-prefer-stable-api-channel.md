---
name: feedback-prefer-stable-api-channel
description: 生成类任务优先走稳定 API 通道（arkcli/SDK），网页浏览器自动化只作兜底且需用户明确同意
metadata:
  type: feedback
---

生成/调用外部服务时优先使用稳定的 API 通道（如 arkcli +gen、SDK REST），不要默认走网页浏览器自动化；浏览器自动化只在 API 不可用且用户明确同意时才用，并要事先说明不稳定性。

**Why:** 2026-09-08 《无音》定妆生成：即梦网页免费额度通道虽跑通（参考图锁脸成功），但连续遭遇 CSP 拦 localhost、隐藏 file input、in-app 浏览器 viewport 失效等问题，用户明确表态"这样太不稳定了，你还是用稳定的 api 通道吧"。

**How to apply:** 遇到"免费额度/网页版"诱惑时先确认 API 是否可用（含余额/开通状态）；API 被账户级闸门（欠费、未开通）卡住时把闸门交还真人（充值/开通链接），而不是自行搭网页自动化绕行。选型时还要看**下游一致性**：2026-09-08 用户在 ARK 欠费背景下选可灵开放平台 key 而非等 ARK 充值，理由是"生成视频的时候保持一致性"（图视频同模型系）——多阶段管线优先选能贯穿各阶段的单一通道。参见 [[reference-ark-account]]、[[jimeng-web-channel]]、[[reference-kling-api]]。
