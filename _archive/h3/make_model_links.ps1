$ErrorActionPreference = 'Stop'
$base = 'D:\AIWorkflow\ComfyUI_H3\ComfyUI\models'
New-Item -ItemType Directory -Force -Path $base | Out-Null
$targets = 'checkpoints','clip','clip_vision','controlnet','diffusion_models','facedetection','facerestore_models','loras','style_models','text_encoders','ultralytics','unet','upscale_models','vae','vae_approx'
foreach ($d in $targets) {
  $link = Join-Path $base $d
  $tgt  = 'D:\Models\ComfyUI\' + $d
  if (-not (Test-Path $link)) {
    New-Item -ItemType Junction -Path $link -Target $tgt | Out-Null
    Write-Output ("created: {0} -> {1}" -f $link, $tgt)
  } else {
    Write-Output ("exists:  {0}" -f $link)
  }
}
Write-Output '--- verify ---'
Get-ChildItem $base | Where-Object { $_.LinkType } | ForEach-Object { "{0}  [{1}] -> {2}" -f $_.Name, $_.LinkType, $_.Target }
