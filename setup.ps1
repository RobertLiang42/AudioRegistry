[CmdletBinding()]
param(
    [string]$Python,
    [switch]$RecreateVenv,
    [switch]$SkipMl,
    [switch]$Cpu,
    [switch]$Dev,
    [switch]$SkipFfmpeg
)

$ErrorActionPreference = 'Stop'
if ($Cpu -and $SkipMl) { throw '-Cpu installs the full ML stack and cannot be combined with -SkipMl.' }
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$RuntimeRoot = Join-Path $ProjectRoot '.runtime'
$RuntimePythonRoot = Join-Path $RuntimeRoot 'python'
$RuntimePython = Join-Path $RuntimePythonRoot 'python.exe'
$CacheRoot = Join-Path $ProjectRoot '.cache\setup'

$PythonVersion = '3.12.10'
$PythonInstallerName = "python-$PythonVersion-amd64.exe"
$PythonInstallerUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonInstallerName"
$PythonInstallerSha256 = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb'

$FfmpegRoot = Join-Path $RuntimeRoot 'ffmpeg'
$FfmpegExe = Join-Path $FfmpegRoot 'bin\ffmpeg.exe'
$FfmpegArchiveName = 'ffmpeg-n7.1.5-12-g1fdbca85aa-win64-lgpl-shared-7.1.zip'
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/$FfmpegArchiveName"
$FfmpegSha256 = '0f376f96fb38554ccefb1b2ae9c7c6a7b351f0e60a372b38262c320e8392c5d0'

function Test-Python312([string]$Executable) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    try {
        $Version = & $Executable -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
        return $LASTEXITCODE -eq 0 -and $Version.Trim() -eq '3.12'
    } catch { return $false }
}

function Test-FfmpegRuntime {
    if (-not (Test-Path -LiteralPath $FfmpegExe -PathType Leaf)) { return $false }
    $FfmpegBin = Split-Path -Parent $FfmpegExe
    $SharedLibrary = Get-ChildItem -LiteralPath $FfmpegBin -Filter 'avutil-*.dll' -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $SharedLibrary) { return $false }
    try {
        $VersionLine = (& $FfmpegExe -version | Select-Object -First 1)
        return $LASTEXITCODE -eq 0 -and $VersionLine -match '^ffmpeg version .*7\.1'
    } catch { return $false }
}

function Install-ProjectPython {
    if ($env:OS -ne 'Windows_NT') {
        throw 'Automatic Python installation currently supports Windows x64 only. Install Python 3.12 and pass -Python.'
    }
    New-Item -ItemType Directory -Force -Path $CacheRoot, $RuntimeRoot | Out-Null
    $Installer = Join-Path $CacheRoot $PythonInstallerName
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf) -or
        (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $PythonInstallerSha256) {
        Write-Host "Downloading Python $PythonVersion..."
        Invoke-WebRequest -Uri $PythonInstallerUrl -OutFile $Installer
    }
    $ActualHash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -ne $PythonInstallerSha256) {
        throw "Python SHA-256 mismatch. Expected $PythonInstallerSha256, received $ActualHash."
    }
    $Signature = Get-AuthenticodeSignature -LiteralPath $Installer
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') {
        throw 'The Python installer does not have a valid Python Software Foundation signature.'
    }
    $Arguments = @(
        '/quiet', 'InstallAllUsers=0', "TargetDir=`"$RuntimePythonRoot`"", 'PrependPath=0',
        'Include_launcher=0', 'Include_test=0', 'Include_doc=0', 'AssociateFiles=0',
        'Shortcuts=0', 'Include_pip=1', 'Include_tcltk=1'
    )
    $Process = Start-Process -FilePath $Installer -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
    if ($Process.ExitCode -notin @(0, 3010)) { throw "Python installer exited with code $($Process.ExitCode)." }
    if (-not (Test-Python312 $RuntimePython)) { throw 'Project-local Python 3.12 installation failed.' }
    Remove-Item -LiteralPath $Installer -Force
}

if ($RecreateVenv -and -not $Python -and -not (Test-Python312 $RuntimePython)) {
    $SystemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $SystemPython -or -not (Test-Python312 $SystemPython.Source)) {
        Install-ProjectPython
    }
}

if ($RecreateVenv -and (Test-Path -LiteralPath $Venv)) {
    $ResolvedVenv = (Resolve-Path -LiteralPath $Venv).Path
    $ExpectedVenv = [IO.Path]::GetFullPath((Join-Path $ProjectRoot '.venv'))
    if ($ResolvedVenv -ne $ExpectedVenv) { throw "Refusing to remove unexpected environment path: $ResolvedVenv" }
    Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    $BootstrapPython = $null
    if ($Python) {
        if (Test-Path -LiteralPath $Python -PathType Leaf) {
            $BootstrapPython = (Resolve-Path -LiteralPath $Python).Path
        } else {
            $Command = Get-Command $Python -ErrorAction SilentlyContinue
            if ($Command) { $BootstrapPython = $Command.Source }
        }
        if (-not (Test-Python312 $BootstrapPython)) { throw '-Python must identify a Python 3.12 executable.' }
    } elseif (Test-Python312 $RuntimePython) {
        $BootstrapPython = $RuntimePython
    } else {
        $SystemPython = Get-Command python -ErrorAction SilentlyContinue
        if ($SystemPython -and (Test-Python312 $SystemPython.Source)) {
            $BootstrapPython = $SystemPython.Source
        } else {
            Install-ProjectPython
            $BootstrapPython = $RuntimePython
        }
    }
    & $BootstrapPython -m venv $Venv
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python build tools.' }
& $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements-core.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install core requirements.' }
if ($Dev) {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements-dev.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install development requirements.' }
}
if ($Cpu) {
    & $VenvPython -m pip install --force-reinstall torch==2.8.0 torchaudio==2.8.0 torchcodec==0.7.0 --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install CPU PyTorch requirements.' }
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements-ml.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install ML requirements.' }
} elseif (-not $SkipMl) {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements-ml.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install ML requirements.' }
}
& $VenvPython -m pip install --no-deps -e $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Failed to install AudioRegistry.' }

if (-not $SkipFfmpeg) {
    if ($env:OS -ne 'Windows_NT') {
        throw 'Automatic FFmpeg installation currently supports Windows x64 only. Install FFmpeg separately and use -SkipFfmpeg.'
    }
    if (-not (Test-FfmpegRuntime)) {
        $Archive = Join-Path $CacheRoot $FfmpegArchiveName
        $Staging = Join-Path $RuntimeRoot ('.ffmpeg-staging-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $CacheRoot, $RuntimeRoot | Out-Null
        try {
            Write-Host 'Downloading pinned FFmpeg 7.1 shared build...'
            Invoke-WebRequest -Uri $FfmpegUrl -OutFile $Archive
            $ActualHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($ActualHash -ne $FfmpegSha256) {
                throw "FFmpeg SHA-256 mismatch. Expected $FfmpegSha256, received $ActualHash."
            }
            Expand-Archive -LiteralPath $Archive -DestinationPath $Staging
            $ExtractedFfmpeg = Get-ChildItem -LiteralPath $Staging -Filter 'ffmpeg.exe' -File -Recurse | Select-Object -First 1
            if (-not $ExtractedFfmpeg) { throw 'The FFmpeg archive did not contain ffmpeg.exe.' }
            $ExtractedRoot = Split-Path -Parent (Split-Path -Parent $ExtractedFfmpeg.FullName)
            if (Test-Path -LiteralPath $FfmpegRoot) {
                Remove-Item -LiteralPath $FfmpegRoot -Recurse -Force
            }
            Move-Item -LiteralPath $ExtractedRoot -Destination $FfmpegRoot
        } finally {
            if (Test-Path -LiteralPath $Staging) { Remove-Item -LiteralPath $Staging -Recurse -Force }
            if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
        }
    }
    $env:PATH = (Split-Path -Parent $FfmpegExe) + [IO.Path]::PathSeparator + $env:PATH
    & $FfmpegExe -version | Select-Object -First 1
}

if ($Cpu) {
    & $VenvPython (Join-Path $ProjectRoot 'scripts\configure-cpu.py')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to save CPU configuration.' }
}

Write-Host "AudioRegistry environment is ready: $Venv"
