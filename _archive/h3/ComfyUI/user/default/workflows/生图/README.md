# 生图 · ComfyUI UI 画布

这是**人工试参数/排障**用的 UI 画布，不是引擎入口。

- `E01_文生图_ZImageTurbo_1MP.json`
  - Z-Image-Turbo 文生图单图：UNETLoader → ModelSamplingAuraFlow → KSampler（8 步、cfg 1.0、res_multistep/simple）→ VAEDecode → SaveImage。
  - 默认 832×1216、seed 42、`filename_prefix=zimage_canvas`；正向提示词是示例，打开后自己改。
  - 负向分支是 `CLIPTextEncode("") → ConditioningZeroOut`，与 `engine/comfy/z_image_turbo_api.json` 一致。

- `E02_图生图_ZImageTurbo.json`
  - Z-Image-Turbo 图生图：**`LoadImage` 节点就是上传源图的地方**（节点里点「选择文件上传」，或从已上传列表选 `wfref_1_T1.png`）。
  - `LoadImage → VAEEncode → KSampler(denoise=0.6)`；实际尺寸由源图决定，画布本身没有单独宽高节点。
  - denoise 0.45–0.70 保构图换风格；0.90 等于重画。默认 seed 42、8 步、`filename_prefix=zimage_i2i_canvas`。
  - 与 `engine/comfy/z_image_i2i_api.json` 一致；负向分支同样是 `ConditioningZeroOut`。

## 真源关系

| 用途 | 真源 |
|---|---|
| 引擎批量出图（面板「文生图」按钮） | `engine/workflows/image_draft_batch.yaml` + `engine/comfy/z_image_turbo_api.json` |
| 引擎批量图生图（面板「图生图」按钮） | `engine/workflows/image_i2i.yaml` + `engine/comfy/z_image_i2i_api.json` |
| 人工在 ComfyUI 里看节点/试参数 | 本目录 E01（文生图）/ E02（图生图） |

⚠ **改画布不等于改 API 模板**：两边是两份文件，改一边不会同步另一边。正式出片仍走 `run.py`（forbidden 第 2 条：agent 不许绕过 run.py 直连 `/prompt`）；这里的画布只供人工排障/试参数。

## 打开方式

ComfyUI 8189 → 工作流菜单 → 打开 `user/default/workflows/生图/E01_文生图_ZImageTurbo_1MP.json` 或 `E02_图生图_ZImageTurbo.json`。
图生图的源图：在 E02 的 `LoadImage` 节点里点「选择文件上传」；上传后节点会显示缩略图，再点运行即可。
如果节点红/缺件，先查 `/object_info` 里对应类是否存在；两张画布生成时已对节点/连线/widget 数做过结构校验（0 错），但**未做 UI 实际打开验收**。
