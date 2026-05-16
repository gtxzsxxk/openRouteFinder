@echo off
title OpenRouteFinder
echo Starting backend...
start "Backend" cmd /k "set PYTHONPATH=%CD% && python -m uvicorn openRouterFinder.api:app --host 0.0.0.0 --port 9807"
echo Starting frontend...
start "Frontend" cmd /k "cd webFinder && npm run dev"
echo.
echo Both servers started.
echo Backend:   http://localhost:9807
echo Frontend:  http://localhost:5173
echo.
pause
