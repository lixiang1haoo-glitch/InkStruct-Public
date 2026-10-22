$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleaseRoot = Join-Path $ProjectRoot "release"
$Target = Join-Path $ReleaseRoot "InkStructCollector"
$Archive = Join-Path $ReleaseRoot "InkStructCollector_portable.zip"

if (-not (Test-Path -LiteralPath "$Target\InkStructCollector.exe")) {
    throw "Portable collector has not been built: $Target"
}

$Files = Get-ChildItem -LiteralPath $Target -Recurse -File |
    Where-Object { $_.FullName -ne (Join-Path $Target "manifest.json") }
$ExeHash = (Get-FileHash -LiteralPath "$Target\InkStructCollector.exe" -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    schema_version = "portable_collector_manifest_v2"
    application = "InkStructCollector"
    platform = "Windows x64"
    packaging = "PyInstaller onedir"
    payload_file_count = $Files.Count
    payload_total_bytes = ($Files | Measure-Object Length -Sum).Sum
    stroke_count_characters = 9574
    stroke_reference_characters = 9574
    stroke_reference_strokes = 112617
    next_stroke_reference = $true
    contains_generator = $false
    contains_pytorch_or_cuda = $false
    executable_sha256 = $ExeHash
    entrypoint = "InkStructCollector.exe"
    symbol_capture = $true
    symbol_sample_schema = "inkstruct_symbol_sample_v1"
    symbol_default_repeats = 5
    symbol_variable_strokes = $true
    bundled_task = "symbols_5.csv"
}
$Manifest | ConvertTo-Json | Set-Content -LiteralPath "$Target\manifest.json" -Encoding utf8

if (Test-Path -LiteralPath $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}
Compress-Archive -LiteralPath $Target -DestinationPath $Archive -CompressionLevel Optimal
$ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Output ($Manifest | ConvertTo-Json -Compress)
Write-Output "archive=$Archive"
Write-Output "archive_bytes=$((Get-Item -LiteralPath $Archive).Length)"
Write-Output "archive_sha256=$ArchiveHash"
