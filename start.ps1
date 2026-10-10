param([string]$Proxy = '', [switch]$InstallGpu, [switch]$InstallModel, [ValidateSet('auto','cpu')][string]$Accelerator = 'auto')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
}
$pipArgs = @('-m', 'pip', 'install', '-r', 'requirements.txt')
if ($Proxy) { $pipArgs += @('--proxy', $Proxy) }
& .venv/Scripts/python.exe @pipArgs
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if ($InstallGpu) {
    $gpuArgs = @('-m', 'pip', 'install', '-r', 'requirements-gpu.txt')
    if ($Proxy) { $gpuArgs += @('--proxy', $Proxy) }
    & .venv/Scripts/python.exe @gpuArgs
    if ($LASTEXITCODE -ne 0) { throw 'Optional GPU dependency installation failed.' }
}
$env:PHOTOCLUSTER_ACCELERATOR = $Accelerator
if ($InstallModel -and -not (Test-Path 'data/models/clip-vision-int8.onnx')) {
    $modelArgs = @('scripts/setup_semantic.py')
    if ($Proxy) { $modelArgs += @('--proxy', $Proxy) }
    & .venv/Scripts/python.exe @modelArgs
    if ($LASTEXITCODE -ne 0) { throw 'Content model setup failed. See README.md.' }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Warning 'FFmpeg/FFprobe are needed for video and damaged-media recovery. Add them to PATH.'
}
Write-Host 'PhotoCluster: http://127.0.0.1:8765'
& .venv/Scripts/python.exe -m uvicorn photocluster.app:app --host 127.0.0.1 --port 8765
