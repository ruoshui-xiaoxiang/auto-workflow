# ============================================================
# Qwen3-14B 鏈湴鑱婂ぉ鏈嶅姟鍚姩鍣紙鐪熸鐨勬墽琛岄€昏緫鍦ㄦ湰鏂囦欢锛?# - 鍚庣: 瀹樻柟 llama.cpp b10721 (Vulkan)銆備笉瑕佺敤 LM Studio 鑷甫鍚庣鈥斺€?#         瀹冨湪鏈€鍚庝竴涓?SSE 鍧楁敞鍏?__lmstudio.model_input锛岄暱 prompt 涓嬩細鎵撳穿 Trae銆?# - 妯″瀷: E:\Models\GGUF\Qwen3-14B-Instruct-Q4_K_M
#         Qwen3-14B-Instruct-Q4_K_M.gguf (Q4閲忓寲, 8.38 GB)
# - 鏈嶅姟: http://127.0.0.1:8081/v1 (OpenAI鍏煎API)
#         妯″瀷鍚?qwen3-14b, 涓婁笅鏂?8192
# - 骞傜瓑: 绔彛1234宸插湪鐩戝惉鍒欏彧鎶ュ憡鐘舵€佺洿鎺ラ€€鍑? 涓嶉噸澶嶅惎鍔?# - 鏃ュ織: E:\LocalAI\logs\llama1234.log / llama1234.err.log
# ============================================================
# One-click start: Qwen3-14B llama-server on port 8081 (official Vulkan backend)
$port = 8081
$exe  = "E:\LocalAI\backends\llama.cpp-b10721-win-vulkan\llama-server.exe"
$model = "E:\Models\GGUF\Qwen3-14B-Instruct-Q4_K_M\Qwen3-14B-Instruct-Q4_K_M.gguf"
$log  = "E:\LocalAI\logs\llama1234.log"
$err  = "E:\LocalAI\logs\llama1234.err.log"

if (-not (Test-Path $exe))   { Write-Host "[ERROR] backend exe not found: $exe" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $model)) { Write-Host "[ERROR] model file not found: $model" -ForegroundColor Red; exit 1 }

$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    Write-Host "[OK] Port $port is already serving. Model ID:" -ForegroundColor Green
    try { $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" -TimeoutSec 5; Write-Host "     $($r.data[0].id)" -ForegroundColor Green } catch {}
    exit 0
}

if (-not (Test-Path "E:\LocalAI\logs")) { New-Item -ItemType Directory -Path "E:\LocalAI\logs" -Force | Out-Null }

Write-Host "Starting Qwen3-14B llama-server on port $port ... (first load ~40-60s)"
Start-Process -FilePath $exe -ArgumentList "--model", $model, "--alias", "qwen3-14b", "--host", "127.0.0.1", "--port", $port, "--n-gpu-layers", "99", "-c", "8192", "--jinja" -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err

# Large GGUF files can take several minutes to load from disk on a cold start.
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Seconds 3
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" -TimeoutSec 3
        Write-Host "[OK] Server ready. Model ID: $($r.data[0].id)" -ForegroundColor Green
        Write-Host "     Endpoint: http://127.0.0.1:$port/v1" -ForegroundColor Green
        exit 0
    } catch {}
}
Write-Host "[ERROR] Startup timeout. Check log: $err" -ForegroundColor Red

