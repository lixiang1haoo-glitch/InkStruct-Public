param(
    [string]$Python = "py",
    [switch]$SkipSubmodules
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
$PythonArguments = @()
if ((Split-Path -Leaf $Python) -in @("py", "py.exe")) {
    $PythonArguments = @("-3.13")
}

if (-not (Test-Path -LiteralPath $EnvironmentPython)) {
    & $Python @PythonArguments -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,14), 'Python 3.12 or 3.13 required'"
    if ($LASTEXITCODE -ne 0) { throw "Unsupported Python" }
    & $Python @PythonArguments -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create virtual environment" }
}
& $EnvironmentPython -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,14), 'Python 3.12 or 3.13 required'"
if ($LASTEXITCODE -ne 0) { throw "Existing virtual environment uses unsupported Python; preserved unchanged" }
if (-not $SkipSubmodules) {
    & git -C $ProjectRoot submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw "Could not initialize pinned submodules" }
}
& $EnvironmentPython -m pip install -e "$ProjectRoot[desktop,dev]"
if ($LASTEXITCODE -ne 0) { throw "Could not install desktop dependencies" }
Write-Output "Environment ready. See docs/COLLABORATION.md for the structure database and collector source pack."
