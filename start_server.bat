@echo off
setlocal
cd /d "%~dp0"
python scripts\server_control.py start
exit /b %ERRORLEVEL%
endlocal
