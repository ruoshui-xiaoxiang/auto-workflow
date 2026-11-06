# 亚洲脸 FLUX LoRA — 数据集与训练记录

## 基础信息

- 项目名：亚洲脸族群向 FLUX LoRA
- 位置（代码根目录）：`E:\LocalAI\`（训练代码在 `sd-scripts\`，工具在 `tools\`，配置在 `configs\`）
- 定位（一句话）：纠正 FLUX.1-dev 的西方人脸偏向，训一个族群向（不锁脸）的亚洲脸 LoRA
- 当前版本 / 里程碑：v1 训练完成（2026-09-05 14:30），4 个 checkpoint 已产出，待验证效果
- 最新更新：2026-11-04 14:18
  （11-04 对账：底模那一行补注——训练时用的是 FLUX.1-dev fp8，原话保留；但该路径盘上已无、
  FLUX 线已退役 ⇒ 这条 FLUX LoRA 挂不上现役 Z-Image-Turbo 链）
- 摘要：702 张精选图 / 149 位中日韩女明星，FLUX.1-dev fp8 底模，LoRA dim=32 alpha=16，训 4 epoch / 704 步，耗时约 4.5 小时。产出 4 个 checkpoint（3 个 epoch + 1 个最终），每个 293MB。待用不同 seed 出图验证：脸不同 = 族群向成功，脸相同 = 过拟合需重训。

## 数据采集

### 采集脚本（按时间顺序）

| 脚本 | 路径 | 数据源 | 结果 |
|---|---|---|---|
| celebrity_scraper.py (v1) | `E:\LocalAI\tools\celebrity_scraper.py` | 百度图片搜索 | 476 张 / 95 人 |
| celebrity_scraper_v2.py | `E:\LocalAI\tools\celebrity_scraper_v2.py` | 百度图片（补充明星 + "年轻"偏好） | +90 张 → 566 张 |
| celebrity_scraper_bing.py | `E:\LocalAI\tools\celebrity_scraper_bing.py` | Bing 图片（高分优先） | +10 张（严重限速） |
| celebrity_scraper_v3.py | `E:\LocalAI\tools\celebrity_scraper_v3.py` | 百度 v3 版本 | 补充采集 |
| celebrity_scraper_tmdb.py | `E:\LocalAI\tools\celebrity_scraper_tmdb.py` | TMDB API（高清剧照） | +464 张（100% >= 768px） |
| curate_training_set.py | `E:\LocalAI\tools\curate_training_set.py` | 精选子集生成 | 702 张 / 149 人（最终训练集） |

### 明星名单

153 位中日韩女明星（72 中国 / 41 韩国 / 40 日本），覆盖经典与新生代。名单硬编码在 `celebrity_scraper_tmdb.py` 中。

### TMDB API

- API Key (v3)：`8b2b5889a364d2af80526d04dbaaa6f6`
- 需要 Clash 代理（`127.0.0.1:7890`）才能从中国大陆访问
- 用搜索 API 自动匹配人物 ID，`append_to_response=images` 获取高清图

### 采集踩坑

- **百度反爬**：需 `requests.Session` + 先访问主页拿 cookie + 完整浏览器指纹 headers（Sec-Fetch-* 等）
- **百度响应格式**：现在返回纯 JSON 而非 JSONP，需兼容两种解析
- **图片格式**：百度返回 webp 但扩展名 .jpg，需 PIL 自动转 jpg
- **objURL 不可用**：百度加密的，需用 thumbURL
- **OpenCV 中文路径**：`cv2.imread()` 无法处理非 ASCII 路径，用 `np.fromfile()` + `cv2.imdecode()` 绕过
- **人脸检测失败**：OpenCV Haar Cascade 对古装/写真/侧脸检测率极低（476 张全部 0 人脸），原图保留未裁剪
- **Bing 限速**：百度和 Bing 都严重限速，Bing 最终只拿到 10 张

## 数据集目录

| 目录 | 内容 | 说明 |
|---|---|---|
| `E:\LocalAI\dataset\asian_faces\` | 1095 张 / 157 人 | 原始采集全量（按 region 分 chinese/japanese/korean 子目录） |
| `E:\LocalAI\dataset\asian_faces_curated\` | 702 张 / 149 人 | 精选子集（每人 3-5 张最高清图，优先 TMDB） |
| `E:\LocalAI\dataset\asian_faces_kohya\` | 702 张 / 149 人 | Kohya 格式（`N_名字` 目录命名，N=重复次数） |
| `E:\LocalAI\dataset\asian_faces_kohya_1024\` | 702 张 | 1024 long-side cap 版本（未用于最终训练） |
| `E:\LocalAI\dataset\asian_faces_kohya_960\` | 702 张 / 149 人 | **最终训练集**，960 long-side cap，64 对齐 |

### 数据集处理流程

1. 原始采集 → `asian_faces/`（按区域分子目录）
2. 精选 → `asian_faces_curated/`（`curate_training_set.py`，每人选 3-5 张最高清图）
3. Kohya 格式 → `asian_faces_kohya/`（目录改为 `1_名字` 格式，生成 .txt caption）
4. 分辨率派生 → `asian_faces_kohya_960/`（长边 cap 960，64 对齐，aspect ratio bucketing）

### Caption 格式

按区域生成通用描述（不写具体明星名字）：
- 中国：`古风女子，汉服，东方五官，...`
- 韩国：`韩国女子，韩服，...`
- 日本：`日本女子，和服，...`

### 数据集质量（精选后 702 张）

- 分辨率（短边）：66.7% >= 768px，38.3% >= 1024px
- 分布：中国 347 张 / 韩国 186 张 / 日本 169 张
- 133 人有 5 张图，12 人少于 5 张（TMDB 图少）

## 训练配置

配置文件：`E:\LocalAI\configs\asian_face_lora.toml`

| 参数 | 值 | 说明 |
|---|---|---|
| 底模 | FLUX.1-dev fp8 | `D:/Models/ComfyUI/diffusion_models/flux1-dev-fp8.safetensors` 〔**11-04 对账**：这一行记的是**当时训练用的底模**，保留不改；但该路径盘上已无，且 FLUX 线 10-19 已退役（底模从没挂进 ComfyUI 模型树）。权重本体在 `E:\Models\ComfyUI`＝可复活资产。⇒ **这条 FLUX LoRA 挂不上现役 Z-Image-Turbo 链**；SDXL 专用 LoRA 只有 `image_draft_batch_sdxl` 那条链能用，Z-Image 侧要挂 LoRA 见 `图片链_工作流规则.md` §3.1「LoRA 供给」〕 |
| 数据集 | `asian_faces_kohya_960` | 702 张 / 149 人 |
| 网络 | LoRA dim=32, alpha=16 | `networks.lora_flux` |
| 训练范围 | UNet only | `network_train_unet_only = true` |
| 优化器 | AdamW8bit | lr=2e-4 |
| 调度器 | cosine_with_restarts | 3 cycles, warmup 100 steps |
| 精度 | bf16 mixed + full_bf16 | fp8_base_unet |
| 批量 | batch_size=1, grad_accum=4 | 有效批量 4 |
| 总步数 | 704 steps (4 epochs) | 176 steps/epoch |
| 加速 | gradient_checkpointing | cache_latents/text_encoder to disk |
| T5 长度 | 32 tokens | `t5xxl_max_token_length = 32` |
| 分辨率 | 960x960 + aspect ratio bucketing | bucket_no_upscale=true |
| 输出 | `E:/LocalAI/lora_output/asian_face_v1/` | 每 epoch 存一次 |

## 训练产出

| Checkpoint | 时间 | 大小 | 说明 |
|---|---|---|---|
| asian_face_community_v1-000001.safetensors | 10:18 | 293MB | Epoch 1 |
| asian_face_community_v1-000002.safetensors | 11:42 | 293MB | Epoch 2 |
| asian_face_community_v1-000003.safetensors | 13:05 | 293MB | Epoch 3 |
| asian_face_community_v1.safetensors | 14:30 | 293MB | 最终（Epoch 4） |

训练总耗时约 4.5 小时（09:00 → 14:30），平均 23.3s/step。

## sd-scripts 代码修改

训练过程中对 `E:\LocalAI\sd-scripts\` 做了以下修改：

### flux_train_network.py（segfault + IndexError 修复）

1. **Segfault 修复**（lines 284-291）：T5-XXL fp8 调用 `.to("cpu")` 会 SIGSEGV（exit 139）。改为 `text_encoders[i] = None` + `gc.collect()`
2. **IndexError 修复**：`del text_encoders[0]` 后 `[1]` 越界。改为 `text_encoders[0] = None`（不删元素）

### train_network.py（None guard）

text encoder 设 None 后 `requires_grad_`/`eval()`/logging 报 AttributeError。三处加 `if t_enc is None: continue`

### library/flux_models.py（SDPA backend workaround）

Blackwell GPU (sm_120) 的 Flash SDPA 不兼容，会 GPU hang。改为显式指定 cuDNN/mem_efficient/math 后端：

```python
from torch.nn.attention import SDPBackend, sdpa_kernel
FLUX_SDPA_BACKENDS = [SDPBackend.CUDNN_ATTENTION, SDPBackend.EFFICIENT_ATTENTION, SDPBackend.MATH]
# attention() 函数内用 sdpa_kernel(FLUX_SDPA_BACKENDS) 包裹
```

### tools/run_training.py（启动器）

训练启动脚本，在 import torch 后立即禁用 Flash SDPA：

```python
torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_mem_efficient_sdp(True)
torch.backends.cuda.enable_cudnn_sdp(True)
torch.backends.cuda.enable_math_sdp(True)
```

## 验证方法

训完后复制到 `D:/Models/ComfyUI/loras/`，用 ComfyUI 加载测试：

- **不同 seed 出图**：脸不同 → 族群向成功（纠正偏向但不锁脸）
- **脸相同** → 过拟合，需重训（扩数据集 / 降 step / 加正则化）

## 当前待办 / 阻塞

- [ ] 用最终 checkpoint 跑测试图，验证族群向效果
- [ ] 如果效果不好，尝试 epoch 1-3 的中间 checkpoint
- [ ] 验证通过后复制到 `D:/Models/ComfyUI/loras/`
- [ ] 如果全部过拟合，考虑重训（降 lr / 减 epoch / 加 dropout）

## 关键路径速查

| 内容 | 路径 |
|---|---|
| 训练配置 | `E:\LocalAI\configs\asian_face_lora.toml` |
| 最终训练集 | `E:\LocalAI\dataset\asian_faces_kohya_960\` |
| 训练产出 | `E:\LocalAI\lora_output\asian_face_v1\` |
| 采集脚本 | `E:\LocalAI\tools\celebrity_scraper*.py` |
| 精选脚本 | `E:\LocalAI\tools\curate_training_set.py` |
| 训练启动器 | `E:\LocalAI\tools\run_training.py` |
| sd-scripts 修改 | `E:\LocalAI\sd-scripts\`（flux_train_network.py, train_network.py, library/flux_models.py） |
| ComfyUI LoRA 目录 | `D:\Models\ComfyUI\loras\` |

## 注意事项 / 踩坑提醒

- **sd-scripts 目录命名约定**：`N_名字` 格式，N 是每 epoch 重复次数（整数）。N 不是整数 → `num_repeats=0` → 目录被跳过 → "No data found"。`1_名字` = 不膨胀。
- **Blackwell GPU SDPA 不兼容 Flash**：必须禁用 Flash SDPA，用 cuDNN/mem_efficient/math，否则 GPU hang（100% util + 40W，不可杀进程，只能重启）。
- **fp8_base_unet 是必须的**：16GB 显存放不下 BF16 全量（22.17 GiB），fp8 压到 ~12GB 才能训。
- **T5-XXL fp8 不能 .to("cpu")**：会 segfault（exit 139），只能设 None + gc.collect()。
- **DataLoader workers 不能多**：32GB RAM 下 4+ workers 会 MemoryError，最终用 0（主进程加载）。
- **TMDB API 需要代理**：中国大陆直连不通，需 Clash（`127.0.0.1:7890`）。
- **Haar Cascade 对古装照无效**：人脸检测率接近 0，不要浪费时间，直接用全图训练。
