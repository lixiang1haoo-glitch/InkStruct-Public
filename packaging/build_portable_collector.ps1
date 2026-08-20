param(
    [string]$OutputRoot = "release"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$CollectorSource = Join-Path (Split-Path -Parent $ProjectRoot) "data_collection"
$BuildRoot = Join-Path $ProjectRoot "artifacts\portable_collector_build"
$StrokeCounts = Join-Path $BuildRoot "stroke_counts.json"
$DistRoot = Join-Path $ProjectRoot $OutputRoot
$PythonBase = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$CondaBin = Join-Path $PythonBase "Library\bin"

if (-not (Test-Path -LiteralPath "$CollectorSource\handwriting_collector\ui.py")) {
    throw "Collector source not found: $CollectorSource"
}

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
& $Python "$PSScriptRoot\export_stroke_counts.py" `
    "$ProjectRoot\artifacts\structures\characters.sqlite3" $StrokeCounts
if ($LASTEXITCODE -ne 0) { throw "Stroke-count export failed" }

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name InkStructCollector `
    --distpath $DistRoot `
    --workpath "$BuildRoot\work" `
    --specpath $BuildRoot `
    --paths $CollectorSource `
    --add-data "$StrokeCounts;." `
    --add-binary "$CondaBin\ffi.dll;." `
    --add-binary "$CondaBin\libbz2.dll;." `
    --add-binary "$CondaBin\libcrypto-3-x64.dll;." `
    --add-binary "$CondaBin\libexpat.dll;." `
    --add-binary "$CondaBin\liblzma.dll;." `
    --add-binary "$CondaBin\libmpdec-4.dll;." `
    --add-binary "$CondaBin\libssl-3-x64.dll;." `
    --exclude-module torch `
    --exclude-module torchvision `
    --exclude-module h5py `
    --exclude-module matplotlib `
    --exclude-module pandas `
    --exclude-module scipy `
    "$PSScriptRoot\portable_collector.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$Target = Join-Path $DistRoot "InkStructCollector"
Copy-Item -LiteralPath "$ProjectRoot\artifacts\collection\user_001\rerecord_current.csv" `
    -Destination "$Target\user_001_rerecord.csv" -Force
Copy-Item -LiteralPath "$PSScriptRoot\PORTABLE_README.txt" `
    -Destination "$Target\使用说明.txt" -Force

$Size = (Get-ChildItem -LiteralPath $Target -Recurse -File | Measure-Object Length -Sum).Sum
Write-Output "Portable collector: $Target"
Write-Output "Bytes: $Size"
