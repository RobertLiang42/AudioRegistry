[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$DotEnvPath = Join-Path $ProjectRoot '.env'
if (Test-Path -LiteralPath $DotEnvPath -PathType Leaf) {
    foreach ($RawLine in [IO.File]::ReadAllLines($DotEnvPath)) {
        $Line = $RawLine.Trim()
        if (-not $Line -or $Line.StartsWith('#')) { continue }
        $Parts = $Line.Split('=', 2)
        if ($Parts.Count -ne 2) { continue }
        $Name = $Parts[0].Trim()
        if ($Name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
        if ([Environment]::GetEnvironmentVariable($Name, 'Process')) { continue }
        $Value = $Parts[1].Trim()
        if ($Value.Length -ge 2 -and (($Value[0] -eq '"' -and $Value[-1] -eq '"') -or ($Value[0] -eq "'" -and $Value[-1] -eq "'"))) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
    }
}
$ActivePython = if ($env:VIRTUAL_ENV) {
    Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
} elseif ($env:CONDA_PREFIX) {
    Join-Path $env:CONDA_PREFIX 'python.exe'
} else {
    $null
}
if ($env:AUDIOREGISTRY_PYTHON) {
    $Python = $env:AUDIOREGISTRY_PYTHON
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "AUDIOREGISTRY_PYTHON does not point to a Python executable: $Python"
    }
} elseif ($ActivePython -and (Test-Path -LiteralPath $ActivePython -PathType Leaf)) {
    $Python = $ActivePython
} elseif (Test-Path -LiteralPath (Join-Path $ProjectRoot '.venv\Scripts\python.exe')) {
    $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw 'Python was not found. Run setup.ps1 or set AUDIOREGISTRY_PYTHON in the local .env file.'
    }
    $Python = $PythonCommand.Source
}

$ManagedFfmpeg = if ($env:AUDIOREGISTRY_FFMPEG) {
    $env:AUDIOREGISTRY_FFMPEG
} elseif ((Test-Path -LiteralPath (Join-Path (Split-Path -Parent $Python) 'Library\bin\ffmpeg.exe') -PathType Leaf) -or
          (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $Python) 'ffmpeg.exe') -PathType Leaf)) {
    $null
} else {
    Join-Path $ProjectRoot '.runtime\ffmpeg\bin\ffmpeg.exe'
}
if ($ManagedFfmpeg -and (Test-Path -LiteralPath $ManagedFfmpeg -PathType Leaf)) {
    $FfmpegBin = Split-Path -Parent $ManagedFfmpeg
    $PathParts = $env:PATH -split [regex]::Escape([IO.Path]::PathSeparator)
    if ($FfmpegBin -notin $PathParts) {
        $env:PATH = $FfmpegBin + [IO.Path]::PathSeparator + $env:PATH
    }
}

$env:MPLCONFIGDIR = Join-Path $ProjectRoot '.cache\matplotlib'
$env:HF_HUB_DISABLE_XET = '1'
& $Python (Join-Path $ProjectRoot 'main.py') @Arguments
exit $LASTEXITCODE
