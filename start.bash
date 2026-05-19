#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# --- Pre-start cleanup ---
echo "Cleaning up old processes..."
# Kill by port (more precise than name matching)
lsof -ti:9807 | xargs kill 2>/dev/null || true
lsof -ti:5173 | xargs kill 2>/dev/null || true
# Also kill by pattern as fallback
pkill -f "uvicorn openRouterFinder.api:app --host 0.0.0.0 --port 9807" 2>/dev/null || true
pkill -f "node.*vite" 2>/dev/null || true
sleep 1

echo "Clearing Python cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

echo "Clearing Vite cache..."
rm -rf webFinder/node_modules/.vite 2>/dev/null || true

echo "Rebuilding frontend dist..."
(cd webFinder && npm run build >/dev/null 2>&1) || echo "Warning: frontend build failed, using existing dist"

echo ""

# --- Start servers ---
cleanup() {
    echo ""
    echo "Shutting down servers..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    exit
}
trap cleanup INT TERM EXIT

echo "Starting backend..."
PYTHONPATH=. python3 -m uvicorn openRouterFinder.api:app --host 0.0.0.0 --port 9807 &
BACKEND_PID=$!

echo "Starting frontend dev server..."
(cd webFinder && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "Both servers started."
echo "Backend:   http://localhost:9807"
echo "Frontend:  http://localhost:5173"
echo "Press Ctrl+C to stop."
echo ""

wait
