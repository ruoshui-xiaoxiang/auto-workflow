# 亚洲脸社区 LoRA 训练计划

## 1. 数据集概况

### 精选训练集
- **位置**: `E:\LocalAI\dataset\asian_faces_curated`
- **总图片**: 702 张
- **人物数**: 149 人（实际有效 133 人 × 5 张 + 少量补充）
- **分布**:
  - 中国: 347 张 (72 人)
  - 韩国: 186 张 (41 人)
  - 日本: 169 张 (44 人)

### 分辨率分布
- 1024px+: 269 张 (38.3%)
- 768-1023px: 199 张 (28.3%)
- 512-767px: 12 张 (1.7%)
- 300-511px: 222 张 (31.6%)
- **高分率 (>=768px)**: 66.7%

### 标注格式
每张图配 `.txt` 文件，内容示例：
- 中国: `古风女子，汉服，古典妆容，东方五官，丹凤眼，鹅蛋脸，写真`
- 韩国: `韩国女子，精致妆容，亚洲五官，鹅蛋脸，写真`
- 日本: `日本女子，精致妆容，亚洲五官，写真`

---

## 2. 训练目标

### 核心目标
训练一个**族群向 LoRA**，修正 FLUX.1-dev 对亚洲面孔的西方偏向，使生成的古风/现代亚洲女性面孔更自然、多样。

### 非目标
- ❌ 不锁定到特定明星脸（避免过拟合）
- ❌ 不生成特定明星的写实照片
- ✅ 学习亚洲面孔的共性特征（五官比例、肤质、妆容风格）

### 成功标准
1. 用相同提示词对比：
   - 无 LoRA: 西方偏向的"亚洲脸"
   - 有 LoRA: 自然的东亚/东南亚面孔
2. 不同 seed 生成不同面孔（不锁定单人）
3. 古风/现代装都能保持亚洲特征

---

## 3. 硬件与环境

### GPU
- **型号**: NVIDIA RTX 5060 Ti
- **显存**: 16GB GDDR7
- **算力**: 约 40 TFLOPS FP16

### 显存估算
- FLUX.1-dev 基础模型: ~12GB (FP16)
- LoRA 训练额外开销: ~3-4GB
- **总需求**: ~15-16GB（接近满载）

### 软件栈
- **训练框架**: kohya-ss/sd-scripts (FLUX LoRA 支持)
- **PyTorch**: 2.3+ (CUDA 12.1+)
- **Python**: 3.10+
- **加速**: xformers / SDPA

---

## 4. 训练配置

### 4.1 基础参数

```yaml
# 模型路径
pretrained_model_name_or_path: "E:/LocalAI/models/flux1-dev.safetensors"
output_dir: "E:/LocalAI/lora_output/asian_face_v1"
output_name: "asian_face_community_v1"

# 数据集
train_data_dir: "E:/LocalAI/dataset/asian_faces_curated"
resolution: "512,768,1024"  # 多分辨率训练
bucket_reso_steps: 64
bucket_no_upscale: true
min_bucket_reso: 512
max_bucket_reso: 1024

# 网络架构
network_dim: 32  # LoRA 维度，32 平衡容量与泛化
network_alpha: 16  # alpha = dim/2，稳定训练
network_module: "networks.lora_flux"

# 训练参数
train_batch_size: 1  # 16GB 显存限制
gradient_accumulation_steps: 4  # 有效 batch = 4
max_train_steps: 3000  # 702 图 × ~4 epoch
optimizer_type: "AdamW8bit"
learning_rate: 2e-4  # LoRA 典型 LR
lr_scheduler: "cosine_with_restarts"
lr_warmup_steps: 100
lr_scheduler_num_cycles: 3

# 精度与加速
mixed_precision: "bf16"  # RTX 50 系推荐 bf16
full_bf16: true
gradient_checkpointing: true  # 省显存
xformers: true  # 或 sdpa: true

# 保存与日志
save_every_n_epochs: 1
save_model_default_dtype: true
logging_dir: "E:/LocalAI/lora_output/asian_face_v1/logs"
log_prefix: "asian_face_v1"
```

### 4.2 关键参数说明

#### 分辨率策略: 多分辨率训练
- **为什么**: 数据集 38% 是 1024px+，32% 是 768-1023px，32% 是低分
- **怎么做**: 每个 batch 随机选 512/768/1024，低分图不放大
- **好处**: 模型学到多尺度特征，避免低分图模糊训练

#### LoRA 维度: 32
- **为什么**: 社区 LoRA 需要足够容量学习 133 人的多样性
- **对比**:
  - dim=16: 容量不足，可能过拟合少数人
  - dim=32: 平衡（推荐）
  - dim=64: 过大，容易过拟合，推理慢

#### 学习率: 2e-4
- **为什么**: LoRA 典型范围 1e-4 ~ 5e-4
- **调优**: 如果 loss 震荡 → 降到 1e-4；如果收敛慢 → 升到 3e-4

#### 步数: 3000
- **计算**: 702 图 × 4 epoch ÷ 4 (gradient accumulation) ≈ 700 steps/epoch × 4 = 2800
- **为什么 4 epoch**: 社区 LoRA 需要多看几遍，但不超过 5（过拟合风险）

#### 有效 batch size: 4
- **为什么**: LoRA 对 batch size 敏感，太小容易过拟合
- **限制**: 16GB 显存只能 batch_size=1，用 gradient_accumulation=4 补偿

---

## 5. 训练流程

### 阶段 1: 准备（10 分钟）
1. 安装 kohya-ss/sd-scripts
   ```bash
   git clone https://github.com/kohya-ss/sd-scripts.git
   cd sd-scripts
   pip install -r requirements.txt
   ```

2. 验证数据集
   ```bash
   python tools/validate_dataset.py \
     --train_data_dir E:/LocalAI/dataset/asian_faces_curated \
     --check_images
   ```

3. 生成缓存（首次训练自动）
   - 图片特征缓存: `latent` 文件
   - 预计耗时: 5-10 分钟

### 阶段 2: 训练（1.5-2 小时）
```bash
accelerate launch --num_cpu_threads_per_process 8 \
  flux_train_network.py \
  --config_file config/asian_face_lora.yaml
```

**监控指标**:
- **Loss**: 应从 0.15 降到 0.05-0.08
  - > 0.10: 学习率太低或数据有问题
  - < 0.03: 可能过拟合
- **显存占用**: 应稳定在 14-15GB
- **速度**: 约 1.5-2 it/s（RTX 5060 Ti）

### 阶段 3: 验证（30 分钟）
每 1 epoch 保存一个 checkpoint，用以下提示词测试：

**测试提示词**:
```
# 古风（训练目标场景）
1girl, hanfu, ancient chinese style, elegant, detailed face, 
asian features, phoenix eyes, oval face, masterpiece, best quality

# 现代（泛化能力测试）
1girl, modern dress, natural makeup, asian face, soft features, 
portrait, photorealistic, 8k

# 负面提示词（固定）
lowres, bad anatomy, bad hands, text, error, missing fingers, 
extra digit, fewer digits, cropped, worst quality, low quality, 
normal quality, jpeg artifacts, signature, watermark, username, blur
```

**验证清单**:
- [ ] 不同 seed (1-10) 生成不同面孔
- [ ] 古风/现代装都保持亚洲特征
- [ ] 不锁定到特定明星（对比刘亦菲/赵丽颖原图）
- [ ] 与无 LoRA 对比，亚洲特征更自然

### 阶段 4: 调优（可选）
如果验证不满意：

| 问题 | 调整 |
|------|------|
| 过拟合（锁定单人） | 降 dim 到 16，减 steps 到 2000 |
| 欠拟合（亚洲特征弱） | 增 steps 到 4000，提 LR 到 3e-4 |
| 低分图模糊 | 提高 min_bucket_reso 到 640 |
| 显存溢出 | 降 resolution 到 "512,768"，开 cache_latents_to_disk |

---

## 6. 预期产出

### 文件结构
```
E:/LocalAI/lora_output/asian_face_v1/
├── asian_face_community_v1_epoch1.safetensors
├── asian_face_community_v1_epoch2.safetensors
├── asian_face_community_v1_epoch3.safetensors
├── asian_face_community_v1_epoch4.safetensors
├── asian_face_community_v1.safetensors (最终)
└── logs/
    └── asian_face_v1_*.log
```

### 推理集成
训练完成后，在 ComfyUI 中使用：
```
# 工作流节点
Load LoRA -> CLIP Text Encode -> KSampler

# 参数
lora_name: asian_face_community_v1.safetensors
strength_model: 0.7-0.9  # 不要 1.0，避免过拟合
strength_clip: 0.7-0.9
```

### 性能预期
- **推理速度**: 与原生 FLUX 相同（LoRA 几乎无开销）
- **显存占用**: +50-100MB（可忽略）
- **效果**: 亚洲面孔自然度提升 30-50%（主观评估）

---

## 7. 风险与缓解

| 风险 | 概率 | 缓解措施 |
|------|------|----------|
| 显存溢出 (OOM) | 中 | 降 resolution 到 768，开 cache_latents_to_disk |
| 过拟合（锁定单人） | 中 | 降 dim/steps，增 dataset 多样性 |
| 欠拟合（效果弱） | 低 | 增 steps 到 4000，提 LR |
| 训练崩溃（loss NaN） | 低 | 检查数据集，降 LR 到 1e-4 |
| 训练时间过长 | 高 | 接受 2 小时，或降 steps 到 2000 |

---

## 8. 后续迭代

### v1.1（如果 v1 不满意）
- 增补数据：用 Bing 补 10 张/人的高分图
- 调整 dim: 16 → 32 或 32 → 64
- 尝试不同 LR schedule: cosine → linear

### v2.0（长期）
- 扩展到男性面孔
- 加入年龄多样性（青年/中年/老年）
- 细分风格（古风/现代/韩系/日系）

---

## 9. 快速启动命令

```bash
# 1. 进入训练目录
cd E:/LocalAI/sd-scripts

# 2. 启动训练
accelerate launch --num_cpu_threads_per_process 8 \
  flux_train_network.py \
  --config_file E:/LocalAI/configs/asian_face_lora.yaml

# 3. 监控（新窗口）
tensorboard --logdir E:/LocalAI/lora_output/asian_face_v1/logs

# 4. 测试（训练完成后）
python E:/LocalAI/tools/test_lora.py \
  --lora_path E:/LocalAI/lora_output/asian_face_v1/asian_face_community_v1.safetensors \
  --prompt "1girl, hanfu, asian features, masterpiece"
```

---

## 10. 检查清单

训练前：
- [ ] 数据集已筛选（702 张，149 人）
- [ ] 标注文件完整（每张图配 .txt）
- [ ] FLUX.1-dev 模型就位（E:/LocalAI/models/flux1-dev.safetensors）
- [ ] kohya-ss/sd-scripts 已安装
- [ ] 显存充足（关闭其他 GPU 程序）

训练中：
- [ ] Loss 正常下降（0.15 → 0.05-0.08）
- [ ] 显存稳定（14-15GB）
- [ ] 无 OOM 或 NaN 错误

训练后：
- [ ] 生成测试图（10 个 seed）
- [ ] 对比无 LoRA 效果
- [ ] 检查是否过拟合（单人锁定）
- [ ] 集成到 ComfyUI 工作流测试

---

**预计总耗时**: 2-2.5 小时（准备 10 分 + 训练 1.5-2 小时 + 验证 30 分）
