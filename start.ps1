param(
    [string]$Proxy = '', [switch]$InstallGpu, [switch]$InstallModel,
    [switch]$NoInstall, [switch]$Check,
    [ValidateSet('auto','cpu')][string]$Accelerator = 'auto',
    [int]$Port = 8765, [string]$Adb = '', [string]$DataDir = ''
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$launchArgs = @('scripts/start.py', '--accelerator', $Accelerator, '--port', "$Port")
if ($Proxy) { $launchArgs += @('--proxy', $Proxy) }
if ($InstallGpu) { $launchArgs += '--install-gpu' }
if ($InstallModel) { $launchArgs += '--install-model' }
if ($NoInstall) { $launchArgs += '--no-install' }
if ($Check) { $launchArgs += '--check' }
if ($Adb) { $launchArgs += @('--adb', $Adb) }
if ($DataDir) { $launchArgs += @('--data-dir', $DataDir) }
$launcher = if (Test-Path '.venv/Scripts/python.exe') { '.venv/Scripts/python.exe' } else { 'python' }
& $launcher @launchArgs
exit $LASTEXITCODE
