[CmdletBinding()]
param([int]$MaximumFileMiB = 20)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath '.git')) {
        throw 'Git repository is not initialized.'
    }
    # Keep non-ASCII paths literal. Git's default C-style quoting is display
    # output and cannot safely be passed back to filesystem APIs.
    $candidatePaths = @(git -c core.quotepath=false ls-files --cached --others --exclude-standard)
    $failed = $false
    $secretPatterns = @(
        'hf_[A-Za-z0-9]{20,}',
        '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        '(?i)(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*["''][^"'']{8,}'
    )
    foreach ($relative in $candidatePaths) {
        $path = Join-Path $ProjectRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $item = Get-Item -LiteralPath $path
        if ($item.Length -gt $MaximumFileMiB * 1MB) {
            Write-Error "Large publish candidate: $relative ($([math]::Round($item.Length / 1MB, 1)) MiB)"
            $failed = $true
        }
        if ($item.Length -le 5MB -and $relative -notmatch '\.(png|jpg|jpeg|gif|ico|woff2?)$') {
            $content = [IO.File]::ReadAllText($path)
            if ($secretPatterns | Where-Object { $content -match $_ }) {
                Write-Error "Possible secret in publish candidate: $relative"
                $failed = $true
            }
            if ($relative -notmatch '^(tests|docs)/' -and $content -match '(?i)[A-Z]:\\(?:Users|Software|conda_envs)\\') {
                Write-Error "Machine-specific absolute path in publish candidate: $relative"
                $failed = $true
            }
        }
    }
    $staged = @(git diff --cached --name-only)
    Write-Host "Publish candidates checked: $($candidatePaths.Count); staged files: $($staged.Count)"
    if ($failed) { exit 1 }
} finally {
    Pop-Location
}
