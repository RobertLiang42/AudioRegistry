@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" webui %*
set "AUDIOREGISTRY_EXIT_CODE=%ERRORLEVEL%"
if not "%AUDIOREGISTRY_EXIT_CODE%"=="0" (
    echo.
    echo AudioRegistry exited with error code %AUDIOREGISTRY_EXIT_CODE%.
    pause
)
exit /b %AUDIOREGISTRY_EXIT_CODE%
