@echo off
setlocal
cd /d "%~dp0"
python scripts\server_control.py stop
exit /b %ERRORLEVEL%
endlocal
