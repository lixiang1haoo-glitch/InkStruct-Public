param(
    [string]$OutputRoot = "release",
    [string]$CollectorSource = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not $CollectorSource) {
    $Candidates = @(
        $env:INKSTRUCT_COLLECTOR_SOURCE,
        (Join-Path $ProjectRoot "artifacts\external\data_collection"),
        (Join-Path (Split-Path -Parent $ProjectRoot) "data_collection")
    )
    $CollectorSource = $Candidates | Where-Object {
        $_ -and (Test-Path -LiteralPath (Join-Path $_ "handwriting_collector\ui.py"))
    } | Select-Object -First 1
}
$BuildRoot = Join-Path $ProjectRoot "artifacts\portable_collector_build"
$StrokeReferences = Join-Path $BuildRoot "stroke_references.json.gz"
$DistRoot = Join-Path $ProjectRoot $OutputRoot
$PythonBase = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$CondaBin = Join-Path $PythonBase "Library\bin"

if (-not (Test-Path -LiteralPath "$CollectorSource\handwriting_collector\ui.py")) {
    throw "Collector source not found: $CollectorSource"
}

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
& $Python "$PSScriptRoot\export_stroke_references.py" `
    "$ProjectRoot\artifacts\structures\characters.sqlite3" $StrokeReferences
if ($LASTEXITCODE -ne 0) { throw "Stroke-reference export failed" }

$BundleArgs = @()
# PyInstaller resolves normal Python DLLs itself; add Conda-specific DLLs only if present.
foreach ($Dll in @("ffi.dll", "libbz2.dll", "libcrypto-3-x64.dll", "libexpat.dll",
                  "liblzma.dll", "libmpdec-4.dll", "libssl-3-x64.dll")) {
    $DllPath = Join-Path $CondaBin $Dll
    if (Test-Path -LiteralPath $DllPath) { $BundleArgs += @("--add-binary", "$DllPath;.") }
}
& $Python -m PyInstaller `
    --noconfirm --clean --onedir --windowed --name InkStructCollector `
    --distpath $DistRoot --workpath "$BuildRoot\work" --specpath $BuildRoot `
    --paths $CollectorSource --paths "$ProjectRoot\src" `
    --add-data "$StrokeReferences;." `
    --collect-data handwriting_collector `
    --exclude-module torch --exclude-module torchvision --exclude-module h5py `
    --exclude-module matplotlib --exclude-module pandas --exclude-module scipy `
    @BundleArgs "$PSScriptRoot\portable_collector.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$Target = Join-Path $DistRoot "InkStructCollector"
$Rerecord = Join-Path $ProjectRoot "artifacts\collection\user_001\rerecord_current.csv"
if (Test-Path -LiteralPath $Rerecord) {
    Copy-Item -LiteralPath $Rerecord -Destination "$Target\user_001_rerecord.csv" -Force
}
Copy-Item -LiteralPath "$ProjectRoot\configs\collection\symbols_5.csv" `
    -Destination "$Target\symbols_5.csv" -Force
Copy-Item -LiteralPath "$PSScriptRoot\PORTABLE_README.txt" `
    -Destination "$Target\使用说明.txt" -Force

$Size = (Get-ChildItem -LiteralPath $Target -Recurse -File | Measure-Object Length -Sum).Sum
Write-Output "Portable collector: $Target"
Write-Output "Bytes: $Size"
