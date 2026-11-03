@echo off
rem Starts Thermo with administrator rights (needed for CPU and SSD temperatures).
net session >nul 2>&1
if %errorlevel% neq 0 (
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    exit /b
)
cd /d "%~dp0"
python -m thermo %*
if errorlevel 1 pause
