param(
    [string]$Source = "C:\Users\lixia\Downloads\数据保存\samples\user_001",
    [switch]$AllSupported
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

Push-Location $ProjectRoot
try {
    & $Python -m inkstruct.cli structures build
    & $Python -m inkstruct.cli samples import $Source --writer user_001
    & $Python -m inkstruct.cli profile build --writer user_001
    if ($AllSupported) {
        & $Python -m inkstruct.cli generate --writer user_001 --all-supported
    } else {
        & $Python -m inkstruct.cli generate --writer user_001 --text "中国书法永湖风鸟"
    }
} finally {
    Pop-Location
}
