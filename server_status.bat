@echo off
setlocal
cd /d "%~dp0"
python scripts\server_control.py status
exit /b %ERRORLEVEL%
endlocal
