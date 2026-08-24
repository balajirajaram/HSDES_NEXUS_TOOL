@echo off
setlocal

REM Launches Auto HSD Analyser UI mode from repository root.
cd /d "%~dp0"

python src\ui_mode.py

endlocal
