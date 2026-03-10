@echo off
echo ============================================
echo   CAT Power Solution - Production Mode
echo ============================================
echo.
echo Step 1: Building frontend...
cd /d "%~dp0frontend"
call npm run build
if errorlevel 1 (
    echo ERROR: Frontend build failed!
    pause
    exit /b 1
)

echo.
echo Step 2: Copying build to static folder...
cd /d "%~dp0"
if exist static rmdir /s /q static
xcopy /E /I /Q "frontend\dist" "static" > nul

echo.
echo Step 3: Starting server on port 8000...
echo.
echo ============================================
echo   App running at: http://localhost:8000
echo   API docs at:    http://localhost:8000/api/docs
echo ============================================
echo.
echo Share this URL with ngrok:
echo   ngrok http 8000
echo.

python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
