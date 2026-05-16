#!/bin/bash
set -e

cd "$(dirname "$0")"

cleanup() {
    echo ""
    echo "Shutting down servers..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit
}
trap cleanup INT TERM EXIT

echo "Starting backend..."
PYTHONPATH=. python3 -m uvicorn openRouterFinder.api:app --host 0.0.0.0 --port 9807 &
BACKEND_PID=$!

echo "Starting frontend..."
cd webFinder && npm run dev &
FRONTEND_PID=$!

echo ""
echo "Both servers started."
echo "Backend:   http://localhost:9807"
echo "Frontend:  http://localhost:5173"
echo "Press Ctrl+C to stop."
echo ""

wait
