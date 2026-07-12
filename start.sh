#!/bin/bash
# PRAVAHA AI Assistant Launcher
# Starts: Ollama (if not running), PRAVAHA backend, and opens browser

cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════"
echo "         PRAVAHA — AI OPERATING SYSTEM"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Disable Datadog APM (causes Python startup hang if agent unreachable)
export DD_TRACE_ENABLED=false
export DD_PROFILING_ENABLED=false
export DD_APM_ENABLED=false

# Check for virtual environment
if [ ! -d "venv" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv venv
fi

echo "[1/4] Activating virtual environment..."
source venv/bin/activate

echo "[2/4] Installing dependencies..."
pip install -q -r requirements.txt 2>/dev/null

# Check if Ollama is running
echo "[3/4] Checking Ollama service..."
if ! curl -s http://localhost:11434 > /dev/null 2>&1; then
    echo "     Ollama not detected. Starting in background..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
    if curl -s http://localhost:11434 > /dev/null 2>&1; then
        echo "     Ollama started successfully."
    else
        echo "     WARNING: Ollama failed to start. Install from ollama.ai"
    fi
else
    echo "     Ollama is already running."
fi

# Pull recommended model if not present
echo "     Checking for AI model..."
if command -v ollama &> /dev/null; then
    ollama list 2>/dev/null | grep -q "hermes3:3b" || {
        echo "     Pulling hermes3:3b model (first time may take a while)..."
        ollama pull hermes3:3b 2>/dev/null &
    }
fi

echo "[4/4] Starting PRAVAHA backend..."
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Say: 'Hey PRAVAHA' to activate"
echo "  Or open: http://localhost:8000"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Start the FastAPI server
echo "     Backend starting on http://localhost:8000 ..."
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..30}; do
  if curl -s http://localhost:8000/ >/dev/null 2>&1; then
    echo "     Backend is ready."
    break
  fi
  sleep 1
done

# Open browser
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open http://localhost:8000/ >/dev/null 2>&1 || true
elif command -v gnome-open >/dev/null 2>&1; then
  gnome-open http://localhost:8000/ >/dev/null 2>&1 || true
fi

echo "═══════════════════════════════════════════════════════════"
echo "  Say: 'Hey PRAVAHA' to activate"
echo "  Or open: http://localhost:8000"
echo "═══════════════════════════════════════════════════════════"
echo ""

wait $SERVER_PID
