param(
    [string]$Python = "C:\Users\lixia\anaconda3\python.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

& $Python -m venv --clear (Join-Path $ProjectRoot ".venv")
& $EnvironmentPython -m pip install --upgrade pip
& $EnvironmentPython -m pip install torch --index-url https://download.pytorch.org/whl/cu128
& $EnvironmentPython -m pip install -e "$ProjectRoot[desktop,dev]" h5py lmdb
& $EnvironmentPython -c "import torch; assert torch.cuda.is_available(); print(torch.__version__, torch.cuda.get_device_name(0))"
& $EnvironmentPython -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
