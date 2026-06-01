Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $backendRoot
$composeFile = Join-Path $projectRoot "docker-compose.mongo.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "Docker was not found. Install Docker Desktop, then run this script again." -ForegroundColor Yellow
  exit 1
}

docker compose -f $composeFile up -d
Write-Host "MongoDB is available at mongodb://127.0.0.1:27017" -ForegroundColor Green
Write-Host "Set MONGODB_FALLBACK_ENABLED=true in backend/.env to enable the app fallback." -ForegroundColor Green
