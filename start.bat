@echo off
title OpenRouteFinder
setlocal enabledelayedexpansion

:: --- Pre-start cleanup ---
echo Cleaning up old processes...

:: Kill processes on port 9807
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :9807') do (
    echo Killing process on port 9807 (PID: %%a)
    taskkill /F /PID %%a 2>nul
)

:: Kill processes on port 5173
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do (
    echo Killing process on port 5173 (PID: %%a)
    taskkill /F /PID %%a 2>nul
)

:: Kill by window title as additional cleanup
taskkill /FI "WINDOWTITLE eq Backend" /F 2>nul
taskkill /FI "WINDOWTITLE eq Frontend" /F 2>nul

timeout /t 2 /nobreak >nul

echo Clearing Python cache...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

echo Clearing Vite cache...
if exist "webFinder\node_modules\.vite" rd /s /q "webFinder\node_modules\.vite" 2>nul

echo Rebuilding frontend dist...
cd webFinder
call npm run build >nul 2>&1
if errorlevel 1 echo Warning: frontend build failed, using existing dist
cd ..

echo.

:: --- Start servers ---
echo Starting backend...
start "Backend" cmd /k "set PYTHONPATH=%CD% && python -m uvicorn openRouterFinder.api:app --host 0.0.0.0 --port 9807"

echo Starting frontend dev server...
start "Frontend" cmd /k "cd webFinder && npm run dev"

echo.
echo Both servers started.
echo Backend:   http://localhost:9807
echo Frontend:  http://localhost:5173
echo.
pause
