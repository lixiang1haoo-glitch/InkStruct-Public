param([Parameter(Mandatory)][string]$Output)
$ErrorActionPreference = 'Stop'
$lock = Get-Content -Raw (Join-Path $PSScriptRoot 'nsis-win.lock.json') | ConvertFrom-Json
if (Test-Path -LiteralPath $Output) { throw "Output already exists: $Output" }
$session = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
$url = $lock.url
for ($attempt = 0; $attempt -lt 4; $attempt++) {
    Invoke-WebRequest -Uri $url -WebSession $session -Headers @{ Referer = $lock.url } -OutFile $Output -TimeoutSec 40
    $digest = (Get-FileHash -LiteralPath $Output).Hash.ToLowerInvariant()
    if ($digest -eq $lock.sha256) {
        Write-Output "Verified NSIS $($lock.version) SHA-256 $digest"
        return
    }
    if ((Get-Item -LiteralPath $Output).Length -gt 512KB) { break }
    # SourceForge sometimes responds with its timed download page.
    $html = Get-Content -Raw -LiteralPath $Output
    $tag = [regex]::Match($html, '(?is)<meta\s+http-equiv="refresh"\s+content="\d+;\s*url=(?<url>https://[^"]+)"')
    if (-not $tag.Success) { break }
    $url = [System.Net.WebUtility]::HtmlDecode($tag.Groups['url'].Value)
    $uri = [uri]$url
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'downloads.sourceforge.net') {
        throw 'The download page did not redirect to the official download host.'
    }
}
throw "SourceForge did not provide the locked NSIS ZIP. Last SHA-256: $digest"
