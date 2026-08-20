@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m inkstruct.generator_app %*
endlocal
