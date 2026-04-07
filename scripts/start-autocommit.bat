@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%auto-commit.ps1" -IntervalSeconds 20 -Branch main -Remote origin
endlocal
