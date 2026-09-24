[CmdletBinding()]
param(
    [ValidateSet('all', 'asr', 'speaker')][string]$Target = 'all',
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Python) {
    $ActivePython = if ($env:VIRTUAL_ENV) {
        Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
    } elseif ($env:CONDA_PREFIX) {
        Join-Path $env:CONDA_PREFIX 'python.exe'
    } else {
        $null
    }
    $VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if ($ActivePython -and (Test-Path -LiteralPath $ActivePython -PathType Leaf)) {
        $Python = $ActivePython
    } elseif (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
        $Python = $VenvPython
    } else {
        $Python = (Get-Command python -ErrorAction Stop).Source
    }
}
if (Test-Path -LiteralPath $Python -PathType Leaf) {
    $Python = (Resolve-Path -LiteralPath $Python).Path
} else {
    $PythonCommand = Get-Command $Python -ErrorAction Stop
    $Python = $PythonCommand.Source
}
$PythonDir = Split-Path -Parent $Python
$HfCandidates = @(
    (Join-Path $PythonDir 'hf.exe'),
    (Join-Path $PythonDir 'Scripts\hf.exe')
)
$Hf = $HfCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $Hf) {
    throw "Hugging Face CLI was not found in the selected Python environment: $Python"
}
$ModelRoot = Join-Path $ProjectRoot 'models'
$env:HF_HUB_DISABLE_XET = '1'

if ($Target -in @('all', 'asr')) {
    & $Hf download Systran/faster-whisper-large-v3 `
        --revision edaa852ec7e145841d8ffdb056a99866b5f0a478 `
        --cache-dir (Join-Path $ModelRoot 'whisper')
    if ($LASTEXITCODE -ne 0) { throw "ASR model download failed with exit code $LASTEXITCODE." }
}
if ($Target -in @('all', 'speaker')) {
    Write-Host 'The pyannote model is gated. Accept its terms and run: hf auth login'
    & $Hf download pyannote/speaker-diarization-community-1 `
        --revision 3533c8cf8e369892e6b79ff1bf80f7b0286a54ee `
        --cache-dir (Join-Path $ModelRoot 'pyannote')
    if ($LASTEXITCODE -ne 0) { throw "Speaker model download failed with exit code $LASTEXITCODE." }
}
