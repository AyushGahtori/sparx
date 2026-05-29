Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $backendRoot

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
  Write-Host "Virtual environment not found. Create it first with:" -ForegroundColor Yellow
  Write-Host "python -m venv .venv" -ForegroundColor Yellow
  exit 1
}

. ".\.venv\Scripts\Activate.ps1"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
