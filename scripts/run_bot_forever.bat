@echo off
REM run_bot_forever.bat
REM Simple wrapper to run the bot in a restart loop and append logs.
REM Run this from the project folder or schedule it at startup.
setlocal enabledelayedexpansion

:: Path to the venv python executable - adjust if your venv path is different
set VENV_PY="%~dp0..\.venv\Scripts\python.exe"
if not exist %VENV_PY% (
  REM fallback to system python if venv not found
  set VENV_PY=python
)

:LOOP
echo ===== Starting bot at %DATE% %TIME% =====
%VENV_PY% "%~dp0..\bot.py" >> "%~dp0..\bot.log" 2>&1
echo ===== Bot exited at %DATE% %TIME% (code: %ERRORLEVEL%) =====
REM Wait a bit before restart to avoid tight crash loop
timeout /t 5 /nobreak > nul
goto LOOP
