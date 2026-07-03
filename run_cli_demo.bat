@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=backend
python scripts\demo_cli.py
exit /b %ERRORLEVEL%
endlocal
