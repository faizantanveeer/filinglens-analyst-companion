@echo off
setlocal EnableDelayedExpansion
rem FilingLens: starts the API and the UI in their own windows, waits until both answer,
rem then opens the browser. Stop with Ctrl+C in each window (or close them).
cd /d "%~dp0"

rem ---- first-run setup ----
if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    python -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements-local.txt || goto :fail
)
if not exist "frontend\node_modules" (
    echo Installing frontend dependencies...
    pushd frontend
    call npm ci || (popd & goto :fail)
    popd
)

rem ---- pick the API port: 8000, or 8001 if 8000 is already in use ----
set "API_PORT=8000"
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul && set "API_PORT=8001"
rem 127.0.0.1, not localhost: uvicorn listens on IPv4 only, and "localhost" tries IPv6 first.
set "API_URL=http://127.0.0.1:%API_PORT%"
echo API will run at %API_URL%

rem ---- start both servers ----
rem No --reload: on Windows its worker process can outlive a closed window and keep holding
rem the port and the local vector-store lock. Use "make api" when you want auto-reload.
start "FilingLens API" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port %API_PORT%"
rem Process env overrides frontend\.env.local, so the UI always points at the API started above.
start "FilingLens UI" cmd /k "cd frontend && set NEXT_PUBLIC_API_URL=%API_URL%&& npm run dev"

rem ---- wait until each server answers (up to 90 s each) ----
<nul set /p "=Waiting for the API "
for /l %%i in (1,1,90) do (
    curl.exe -s -o nul -m 2 "%API_URL%/health" && goto :api_up
    <nul set /p "=."
    ping -n 2 127.0.0.1 >nul
)
echo.
echo The API did not start. Check the "FilingLens API" window for the error.
pause
exit /b 1
:api_up
echo  ready

<nul set /p "=Waiting for the UI "
for /l %%i in (1,1,90) do (
    curl.exe -s -o nul -m 2 "http://127.0.0.1:3000" && goto :ui_up
    <nul set /p "=."
    ping -n 2 127.0.0.1 >nul
)
echo.
echo The UI did not start. Check the "FilingLens UI" window for the error.
pause
exit /b 1
:ui_up
echo  ready

start "" http://localhost:3000
exit /b 0

:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
