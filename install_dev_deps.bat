@echo off
setlocal
cd /d "%~dp0"
python -m pip install -e .[dev]
exit /b %ERRORLEVEL%
endlocal
