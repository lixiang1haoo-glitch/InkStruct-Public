@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m inkstruct.table_editor.app %*
endlocal
