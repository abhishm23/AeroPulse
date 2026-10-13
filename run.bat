@echo off
title AeroPulse // Tactical Flight Anomaly Engine

:: Change to the directory where this .bat file lives
cd /d "%~dp0"

echo ===========================================================
echo   AEROPULSE // TACTICAL FLIGHT ANOMALY ENGINE
echo   Dashboard: http://localhost:8000/
echo   Telemetry: http://localhost:8000/api/telemetry
echo ===========================================================
echo.

:: Kill any existing process on port 8000
echo Clearing port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 >nul 2>&1 || ping 127.0.0.1 -n 2 >nul

echo Starting AeroPulse server on port 8000...
echo.

:: Open browser after server binds
start "" cmd /c "timeout /t 2 >nul 2>&1 & start http://localhost:8000/"

:: Launch uvicorn main:app
python -m uvicorn main:app --host 0.0.0.0 --port 8000

:: If uvicorn exits with an error, pause
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Server failed to start.
    pause
)
