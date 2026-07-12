Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "         PRAVAHA - AI OPERATING SYSTEM (Windows)" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host ""

# Check for virtual environment
if (-not (Test-Path "venv")) {
    Write-Host "[1/4] Creating virtual environment..." -ForegroundColor Yellow
    $hermesPython = "C:\Users\doesn\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
    if (Test-Path $hermesPython) {
        Write-Host "     Using Python 3.11 from hermes-agent to ensure PyAudio wheel compatibility..." -ForegroundColor Green
        & $hermesPython -m venv venv
    }
    else {
        python -m venv venv
    }
}

Write-Host "[2/4] Installing dependencies..." -ForegroundColor Yellow
& .\venv\Scripts\pip.exe install -r requirements.txt

# Check if Ollama is running
Write-Host "[3/4] Checking Ollama service..." -ForegroundColor Yellow
$ollamaRunning = $false
try {
    $null = Invoke-RestMethod -Uri "http://localhost:11434" -TimeoutSec 2
    $ollamaRunning = $true
}
catch {
    # Not running
}

if (-not $ollamaRunning) {
    Write-Host "     Ollama not detected. Starting in background..." -ForegroundColor Magenta
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    try {
        $null = Invoke-RestMethod -Uri "http://localhost:11434" -TimeoutSec 2
        Write-Host "     Ollama started successfully." -ForegroundColor Green
    }
    catch {
        Write-Host "     WARNING: Ollama failed to start. Install from ollama.ai" -ForegroundColor Red
    }
}
else {
    Write-Host "     Ollama is already running." -ForegroundColor Green
}

# Pull model
Write-Host "     Checking for AI model..." -ForegroundColor Yellow
& ollama pull hermes3:3b

Write-Host "[4/4] Starting PRAVAHA backend..." -ForegroundColor Yellow
Write-Host ""
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "  Say: 'Hey PRAVAHA' to activate"
Write-Host "  Or open: http://localhost:8000"
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host ""

& .\venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --reload
