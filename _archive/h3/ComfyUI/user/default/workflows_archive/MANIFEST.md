# 工作流归档（2026-10-21）

## C_逐镜_Ref2VA_MSB / C02_逐镜_Ref2VA_MSB_Krea2缺件.json

- **原路径**：`D:\AIWorkflow\ComfyUI_H3\ComfyUI\user\default\workflows\C_逐镜_Ref2VA_MSB\C02_逐镜_Ref2VA_MSB_Krea2缺件.json`
- **归档路径**：`D:\AIWorkflow\ComfyUI_H3\ComfyUI\user\default\workflows_archive\C_逐镜_Ref2VA_MSB\C02_逐镜_Ref2VA_MSB_Krea2缺件.json`
- **sha256**：`7c6aa1e427b976f4d1b7369ea349651a0c2a5ce894b1b21cf0fe3643a401500f`
- **原因**：Krea2 选角线从未实测；缺两件核心模型：
  - `Krea2/Krea2_Turbo_convrot_int8mixed.safetensors`（UNET，HF 对应 `Comfy-Org/Krea-2/diffusion_models/krea2_turbo_int8_convrot.safetensors`，13.5G，未下载）
  - `Krea2/krea2_charactersheet_full_v1.safetensors`（角色表 LoRA，HF 无同名来源）
- **已补齐且仍保留在模型库**：`taeh3.safetensors`（vae_approx）、`Qwen/qwen_image_vae.safetensors`（vae）
- **恢复方法**：把本文件复制回 `workflows\C_逐镜_Ref2VA_MSB\`，刷新 ComfyUI 工作流列表即可。
- **恢复前注意**：画布内 `ModelPreviewOverrideKJ` 的 `preview_frames` 是 1024，若启用预览会严重拖慢采样，建议先改成 1。

## _bak / C01_逐镜_Ref2VA_MSB_主用.json.bak-20261019

- **原路径**：`workflows\C_逐镜_Ref2VA_MSB\C01_逐镜_Ref2VA_MSB_主用.json.bak-20261019`
- **sha256**：`3c2eff8e0a58df391b70778c4f817f3878b275f861f00e61d617de60cace7233`
- **原因**：旧版备份文件，会混在 ComfyUI 工作流列表里，移出日常列表；文件原样保留。

归档时间：2026-10-21 01:35
