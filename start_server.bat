@echo off
setlocal
cd /d "%~dp0"
python scripts\server_control.py start %*
set EXITCODE=%ERRORLEVEL%
endlocal & exit /b %EXITCODE%
