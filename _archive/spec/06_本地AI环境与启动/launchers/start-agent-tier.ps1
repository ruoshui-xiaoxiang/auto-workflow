param(
    [ValidateSet(1,2,3)] [int]$Tier = 1,
    [int]$Port = 8082,
    [int]$Ctx = 0,
    [ValidateSet('default','minimal','low','medium','high','xhigh','max')]
    [string]$Effort = 'low',
    [switch]$Draft,
    [switch]$PrintArgs
)
$ErrorActionPreference = 'Stop'

# 三档本地 agent 服务：只按显存/内存余量分档，每档内取该预算下的最佳配置。
# 实测数字（2026-08-31，Vulkan 后端，桌面空载已占 ~1980 MiB 显存 / 空闲显存上限 14070 MiB）：
#   1 = gpt-oss-20b 全进显存 + 65536   净显存 11957 MiB，常驻内存 11.2 GB，解码 114 tok/s
#   2 = gpt-oss-20b 专家卸内存 + 65536  净显存  2354 MiB，常驻内存  4.3 GB（另需 ~12 GB 页缓存），解码 27 tok/s
#   3 = Qwen2.5-7B        + 16384      净显存  4780 MiB，常驻内存  4.4 GB，解码 82 tok/s
# 三档工具调用实测均 25/25（3 工具池 / 双工具 / 两轮链路，n=5）。第 3 档过不了 41k 请求：16384 直接 HTTP 400。
# -Draft（EAGLE3）实测是负收益，别开：16384 下解码 67 tok/s vs 同上下文对照 115 tok/s，
#   草稿接受率仅 27%、平均长度 1.80，多烧 1119 MiB 显存却换来 1.7 倍减速。

$GGUF  = 'E:\Models\GGUF'
$MODEL = @{
    1 = "$GGUF\gpt-oss-20b-MXFP4\gpt-oss-20b-MXFP4.gguf"
    2 = "$GGUF\gpt-oss-20b-MXFP4\gpt-oss-20b-MXFP4.gguf"
    3 = "$GGUF\Qwen2.5-7B-Instruct-Q4_K_M\Qwen2.5-7B-Instruct-Q4_K_M.gguf"
}
$DRAFT_FILE = "$GGUF\eagle3-gpt-oss-20b-Q8_0\eagle3-gpt-oss-20b-Q8_0.gguf"
$ALIAS  = @{ 1='gpt-oss-20b-t1'; 2='gpt-oss-20b-t2'; 3='qwen2.5-7b' }
$CTX_BY_TIER = @{ 1=65536; 2=65536; 3=16384 }
# 闸门按实测净显存上调 15% 余量：档 2 只需 2354(权重) + ~1500(65k q8_0 KV)，
# 原先拍脑袋写的 6200 会让它在本能起得来的机器上直接拒绝启动。
$NEEDMB = @{ 1=13600; 2=5200; 3=5600 }

$ctxLen = if ($Ctx -gt 0) { $Ctx } elseif ($Draft) { 32768 } else { $CTX_BY_TIER[$Tier] }
$need = $NEEDMB[$Tier] + $(if ($Draft) { 1000 } else { 0 })

function Resolve-LlamaServer {
    # 必须优先官方原版：LM Studio 魔改的 llama-server-impl.dll 会在最后一个 SSE 块注入
    # __lmstudio.model_input（整个渲染后 prompt 的回显）。Trae 的 prompt ~23k token 时
    # 该行实测 138608 字符，超 Trae Go 运行时 bufio.Scanner 的 64KB 上限，
    # 导致每轮报 "failed to recv http server response: bufio.Scanner: token too long" 并无限撤回重发。
    $official = 'E:\LocalAI\backends'
    foreach ($dir in 'llama.cpp-*cuda*\llama-server.exe', 'llama.cpp-*vulkan*\llama-server.exe') {
        $hit = Get-ChildItem -Path "$official\$dir" -ErrorAction SilentlyContinue |
               Sort-Object Name -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    # 回退到 LM Studio 后端（其 model_input 注入会打崩 Trae，仅应急）。
    $root = "$env:USERPROFILE\.lmstudio\extensions\backends"
    foreach ($dir in 'llama.cpp-win-x86_64-cuda*avx2-*', 'llama.cpp-win-x86_64-vulkan-avx2-*') {
        $hit = Get-ChildItem -Path "$root\$dir\llama-server.exe" -ErrorAction SilentlyContinue |
               Sort-Object Name -Descending | Select-Object -First 1
        if ($hit) {
            Write-Warning '用的是 LM Studio 魔改后端，它注入的 __lmstudio.model_input 会让 Trae 报 token too long。装官方原版到 E:\LocalAI\backends 可解。'
            return $hit.FullName
        }
    }
    throw "找不到 llama-server.exe。把 llama.cpp 官方 win-vulkan 版解压到 E:\LocalAI\backends\，或在 LM Studio 设置里下载 llama.cpp 后端。"
}

$server = Resolve-LlamaServer
$backendKind = if ($server -match 'cuda') { 'CUDA' } else { 'VULKAN' }
$help = (& $server --help 2>&1) | Out-String
function Has-Flag([string]$name) { return $help -match [regex]::Escape($name) }

$model = $MODEL[$Tier]
Write-Host "[$backendKind] $server" -ForegroundColor Cyan
Write-Host "档位 $Tier / $(Split-Path $model -Leaf) / $ctxLen" -ForegroundColor Cyan

if ($Tier -in 1,2 -and $backendKind -eq 'VULKAN') {
    Write-Warning '第 1/2 档正跑在 Vulkan 上，MoE/mxfp4 会明显偏慢。LM Studio 设置 > 推理引擎 里换 CUDA 12 后端（backend-preferences-v1.json 目前钉在 vulkan）。'
}
if (-not (Test-Path $model)) {
    throw "缺模型文件：$model`n第 1/2 档需要先下 ggml-org/gpt-oss-20b-GGUF 的 gpt-oss-20b-MXFP4.gguf (12.11 GB)。"
}

$free = [int](& nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits)
Write-Host "空闲显存 $free MiB，本档约需 $need MiB" -ForegroundColor Cyan
if ($free -lt $need) {
    throw "显存不足：还差 $($need - $free) MiB。卸载 LM Studio 里已加载的模型、去掉 -Draft、或用 -Ctx 调小上下文，再或降到更低档位。"
}

$params = @(
    '-m', $model,
    '--alias', $ALIAS[$Tier],
    '-c', $ctxLen,
    '--n-gpu-layers', 99,
    '--host', '127.0.0.1', '--port', $Port,
    '--parallel', 1
)
# q8_0 KV：占用减半、质量损失可忽略，是 16GB 卡开长上下文的前提。
if ((Has-Flag '--cache-type-k') -and (Has-Flag '--cache-type-v')) {
    $params += @('--cache-type-k','q8_0','--cache-type-v','q8_0')
}
if (Has-Flag '--flash-attn') { $params += @('--flash-attn','on') }
# --jinja 决定成败：不带它，模型不会按 Harmony/ChatML 发 tool_calls，Trae 侧永远收不到工具调用。
if (Has-Flag '--jinja') { $params += '--jinja' }
# gpt-oss 的思考长度是尾部风险：实测 effort=high 会烧满 4000 token 全在想、答案 0 字符。
# Trae 不在请求体里传 reasoning_effort，所以只能在服务端定默认；请求真传了会以请求为准。
if ($Tier -ne 3 -and (Has-Flag '--reasoning-effort')) {
    $params += @('--reasoning-effort', $Effort)
}

if ($Tier -eq 2) {
    # 24 层专家全部放内存：显存只需 ~3.6 GiB 权重（注意力/嵌入/router 保 bf16 未量化），
    # 换来同一颗模型 + 同 65k 上下文，代价是解码吞吐降到约 1/3。
    if (Has-Flag '--n-cpu-moe') { $params += @('--n-cpu-moe', 24) }
    else { Write-Warning '该构建不支持 --n-cpu-moe，第 2 档退化为全 GPU（显存占用同第 1 档）。' }
}
if ($Tier -eq 1 -and $Draft) {
    if (-not (Test-Path $DRAFT_FILE)) { throw "-Draft 需要 $DRAFT_FILE" }
    if (Has-Flag '--model-draft') {
        $params += @('--model-draft', $DRAFT_FILE)
        # Has-Flag 只能证明标志存在，证明不了取值合法：2.31.2 的 --spec-type 只认 draft-eagle3，
        # 传 eagle3 会直接 "unknown speculative type" 起不来。从 --help 里反查该构建实际广告的名字。
        $specVal = @('draft-eagle3','eagle3') | Where-Object { Has-Flag $_ } | Select-Object -First 1
        if ($specVal) { $params += @('--spec-type', $specVal) }
        else { Write-Warning '该构建的 --spec-type 没有 eagle3 取值，已跳过投机解码。' }
        Write-Host "EAGLE3 草稿已启用，上下文已压到 32768" -ForegroundColor Green
    } else { Write-Warning '该构建不支持 --model-draft，已忽略 -Draft。' }
}

Write-Host "`nTrae 自定义模型填：Base URL = http://127.0.0.1:$Port/v1 ，Model ID = $($ALIAS[$Tier])" -ForegroundColor Yellow

if ($PrintArgs) {
    # 供一键启动器复用：闸门/参数探测都已经跑过了，这里只把结果交出去，让它后台起服务。
    "SERVER:$server"
    foreach ($p in $params) { "PARAM:$p" }
    exit 0
}

Write-Host "$server $($params -join ' ')`n" -ForegroundColor DarkGray
& $server @params

