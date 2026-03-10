@echo off
echo ============================================
echo   CAT Power Solution - Share Publicly
echo ============================================
echo.

:: Step 1: Build frontend
echo Step 1: Building frontend...
cd /d "%~dp0frontend"
call npm run build
cd /d "%~dp0"
if exist static rmdir /s /q static
xcopy /E /I /Q "frontend\dist" "static" > nul

:: Step 2: Start production server
echo.
echo Step 2: Starting production server on port 8000...
start "CAT-Server" cmd /c "cd /d "%~dp0" && python -m uvicorn api.main:app --host 0.0.0.0 --port 8000"
timeout /t 4 /nobreak > nul

:: Step 3: Create public tunnel
echo.
echo Step 3: Creating public tunnel...

:: Try ngrok first (if user has it configured)
where ngrok > nul 2>&1
if not errorlevel 1 (
    echo Using ngrok for tunnel...
    echo ============================================
    echo   Share the https URL shown below!
    echo ============================================
    echo.
    ngrok http 8000
    goto :end
)

:: Fall back to localtunnel (no signup needed)
echo Using localtunnel (no signup required)...
echo.
echo ============================================
echo   The public URL will appear below.
echo   Share it with anyone to access the app!
echo.
echo   NOTE: First-time visitors must click
echo   "Click to Continue" on the landing page.
echo ============================================
echo.
npx --yes localtunnel --port 8000

:end
echo.
echo Server stopped. Cleaning up...
taskkill /FI "WINDOWTITLE eq CAT-Server" > nul 2>&1
