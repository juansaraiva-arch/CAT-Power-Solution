@echo off
echo ============================================
echo   CAT Power Solution - Development Mode
echo ============================================
echo.
echo Starting Backend (port 8000) and Frontend (port 5173)...
echo.

:: Start backend in background
start "CAT-Backend" cmd /c "cd /d "%~dp0" && python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000"

:: Wait for backend to start
timeout /t 3 /nobreak > nul

:: Start frontend
start "CAT-Frontend" cmd /c "cd /d "%~dp0frontend" && npx vite --port 5173 --host"

echo.
echo Backend:  http://localhost:8000/api/docs
echo Frontend: http://localhost:5173
echo.
echo Press any key to stop both servers...
pause > nul

:: Kill servers
taskkill /FI "WINDOWTITLE eq CAT-Backend*" /F > nul 2>&1
taskkill /FI "WINDOWTITLE eq CAT-Frontend*" /F > nul 2>&1
echo Servers stopped.
