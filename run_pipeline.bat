@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Please install Python and add it to PATH.
    exit /b 1
)

if not exist "output" mkdir "output"
if not exist "output\runtime\logs" mkdir "output\runtime\logs"

echo ======================================
echo Starting pipeline
echo Logs are managed by scripts\pdf_extraction\run_pipeline.py
echo ======================================

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "& { $env:PYTHONIOENCODING='utf-8'; & python 'scripts/pdf_extraction/run_pipeline.py' @args; exit $LASTEXITCODE }" %*

set "EXIT_CODE=%ERRORLEVEL%"

echo ======================================
echo Pipeline finished with exit code: %EXIT_CODE%
echo Check output\runtime\logs for the generated log file
echo ======================================

exit /b %EXIT_CODE%
