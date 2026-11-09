param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Output
)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Run only on a disposable GitHub-hosted Windows VM.'
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$Output = (New-Item -ItemType Directory -Path $Output).FullName
$runtime = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
$libraries = 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'

function RuntimeState {
    $key = Get-ItemProperty -LiteralPath $runtime -ErrorAction SilentlyContinue
    $files = [ordered]@{}
    foreach ($library in $libraries) {
        $file = Get-Item -LiteralPath "$env:SystemRoot\System32\$library" -ErrorAction SilentlyContinue
        $files[$library] = if ($file) { $file.VersionInfo.FileVersion } else { $null }
    }
    [ordered]@{ installed = $key.Installed; version = $key.Version; system_files = $files }
}

function Run([string]$Program, [string[]]$Arguments) {
    (Start-Process -FilePath $Program -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru).ExitCode
}

function IsMicrosoftExecutable([string]$Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    $signature.Status -eq 'Valid' -and $signature.SignerCertificate.Subject -match 'Microsoft Corporation'
}

$before = RuntimeState
$download = Join-Path $Output 'vc-redist-x64.exe'
Invoke-WebRequest -Uri 'https://aka.ms/vc14/vc_redist.x64.exe' -OutFile $download
if (-not (IsMicrosoftExecutable $download)) {
    throw 'Microsoft redistributable signature could not be verified.'
}
$runtimeHash = (Get-FileHash -LiteralPath $download).Hash.ToLowerInvariant()

# The Microsoft bootstrapper owns the dependency registration for both MSIs.
$uninstallRoots = @(
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$bundles = Get-ItemProperty $uninstallRoots |
    Where-Object {
        $_.Publisher -eq 'Microsoft Corporation' -and $_.DisplayVersion -like '14.*' -and
        $_.DisplayName -match '^Microsoft Visual C\+\+ .+ Redistributable \(x64\)'
    }
$removed = @()
$cache = [IO.Path]::GetFullPath((Join-Path $env:ProgramData 'Package Cache')) + '\'
foreach ($bundle in $bundles) {
    $command = [regex]::Match([string]$bundle.QuietUninstallString, '^"(?<path>[^"]+)"\s+/uninstall\s+/quiet')
    if (-not $command.Success) { continue }
    $cached = [IO.Path]::GetFullPath($command.Groups['path'].Value)
    if ($cached.StartsWith($cache, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $cached -PathType Leaf) -and (IsMicrosoftExecutable $cached)) {
        $code = Run $cached @('/uninstall', '/quiet', '/norestart', '-burn.ignoredependencies=ALL')
        $removed += [ordered]@{ name = $bundle.DisplayName; version = $bundle.DisplayVersion; exit = $code }
    }
}
if ((RuntimeState).installed -eq 1) {
    $code = Run $download @('/uninstall', '/quiet', '/norestart', '-burn.ignoredependencies=ALL')
    $removed += [ordered]@{ name = 'Microsoft download'; version = (Get-Item $download).VersionInfo.FileVersion; exit = $code }
}

# Some images also install the same runtime directly as individual MSIs.
$products = Get-ItemProperty $uninstallRoots[1] |
    Where-Object {
        $_.Publisher -eq 'Microsoft Corporation' -and $_.DisplayVersion -like '14.*' -and
        $_.DisplayName -match '^Microsoft Visual C\+\+ .+ X64 (Minimum|Additional) Runtime\b' -and
        $_.PSChildName -match '^\{[0-9A-Fa-f-]{36}\}$'
    }
foreach ($product in $products) {
    $code = Run "$env:SystemRoot\System32\msiexec.exe" @('/x', $product.PSChildName, '/qn', '/norestart')
    $removed += [ordered]@{ name = $product.DisplayName; version = $product.DisplayVersion; exit = $code }
    if ($code -notin @(0, 1605)) { throw "Could not remove $($product.DisplayName). Exit code $code." }
}
Write-Output ($removed | ConvertTo-Json -Compress)
$held = @()
$heldKey = "$runtime.inkstruct-ci-hold"
$absenceMethod = 'microsoft-uninstall'
$restoreAction = '/install'
$runtimeKeyHeld = $false
try {
    $remaining = RuntimeState
    if ($remaining.installed -eq 1 -or ($remaining.system_files.Values | Where-Object { $_ })) {
        # Visual Studio dependencies can keep the redistributable registered.
        # On this disposable VM, hold only the application's known x64 runtime
        # files and detection key. The real installer must see missing files.
        $absenceMethod = 'held-runtime-files-and-registration'
        $restoreAction = '/repair'
        $system32 = (Resolve-Path -LiteralPath "$env:SystemRoot\System32").Path
        foreach ($library in $libraries) {
            $path = Join-Path $system32 $library
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
            $file = Get-Item -LiteralPath $path
            if ($file.DirectoryName -ne $system32 -or $file.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint) -or
                $file.VersionInfo.OriginalFilename -ne $library -or -not (IsMicrosoftExecutable $path) -or
                (Test-Path -LiteralPath "$path.inkstruct-ci-hold")) {
                throw "Unexpected runtime file at $path"
            }
            Rename-Item -LiteralPath $path -NewName "$library.inkstruct-ci-hold"
            $held += $path
        }
        if (Test-Path -LiteralPath $runtime) {
            if (Test-Path -LiteralPath $heldKey) { throw 'Unexpected held runtime key' }
            Rename-Item -LiteralPath $runtime -NewName 'x64.inkstruct-ci-hold'
            $runtimeKeyHeld = $true
        }
    }

    $absent = RuntimeState
    Write-Output ("$absenceMethod " + ($absent | ConvertTo-Json -Compress))
    if ($absent.installed -eq 1 -or ($absent.system_files.Values | Where-Object { $_ })) {
        throw 'The x64 runtime is still available.'
    }
    $target = Join-Path $Output 'should-not-be-installed'
    $missingExit = Run $Installer @('/S', '/ISOLATED', "/D=$target")
    if ($missingExit -ne 10 -or (Test-Path -LiteralPath $target)) {
        throw "Missing runtime did not stop installation cleanly. Exit code $missingExit."
    }

    if ($runtimeKeyHeld) {
        Rename-Item -LiteralPath $heldKey -NewName 'x64'
        $runtimeKeyHeld = $false
    }
    $installExit = Run $download @($restoreAction, '/quiet', '/norestart')
    if ($installExit -notin @(0, 3010)) { throw "Microsoft redistributable failed. Exit code $installExit." }
    $after = RuntimeState
    if ($after.installed -ne 1 -or $after.system_files.Values -contains $null) {
        throw ("The downloaded Microsoft runtime did not restore every file: " + ($after | ConvertTo-Json -Compress))
    }
} finally {
    if ($runtimeKeyHeld) { Rename-Item -LiteralPath $heldKey -NewName 'x64' }
    foreach ($path in $held) {
        if (-not (Test-Path -LiteralPath $path)) {
            Rename-Item -LiteralPath "$path.inkstruct-ci-hold" -NewName (Split-Path -Leaf $path)
        }
    }
}
[ordered]@{
    runner = $env:ImageOS
    runner_image = $env:ImageVersion
    windows_build = [Environment]::OSVersion.Version.ToString()
    before = $before
    removed = $removed
    absent = $absent
    absence_method = $absenceMethod
    missing_runtime_exit = $missingExit
    no_partial_install = $true
    microsoft_download_sha256 = $runtimeHash
    microsoft_restore_action = $restoreAction
    microsoft_install_exit = $installExit
    after = $after
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $Output 'clean-runtime.json')
