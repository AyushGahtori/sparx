Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $backendRoot
$composeFile = Join-Path $projectRoot "docker-compose.mongo.yml"
$dataDir = Join-Path $backendRoot ".mongodb-data\db"
$logDir = Join-Path $backendRoot "logs"
$logFile = Join-Path $logDir "mongod.log"
$port = 27017

function Test-MongoListener {
  return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (Test-MongoListener) {
  Write-Host "MongoDB is already listening at mongodb://127.0.0.1:$port" -ForegroundColor Green
  exit 0
}

function Find-MongoD {
  $command = Get-Command mongod -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }

  $candidates = @(
    (Join-Path $projectRoot "tools\mongodb"),
    "C:\Program Files\MongoDB"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      $match = Get-ChildItem $candidate -Recurse -Filter mongod.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
      if ($match) {
        return $match.FullName
      }
    }
  }
  return $null
}

$mongod = Find-MongoD
if ($mongod) {
  New-Item -ItemType Directory -Force -Path $dataDir, $logDir | Out-Null
  Start-Process -FilePath $mongod -ArgumentList @(
    "--dbpath", $dataDir,
    "--bind_ip", "127.0.0.1",
    "--port", "$port",
    "--logpath", $logFile,
    "--logappend"
  ) -WindowStyle Hidden
  Start-Sleep -Seconds 5
  if (Test-MongoListener) {
    Write-Host "MongoDB is available at mongodb://127.0.0.1:$port" -ForegroundColor Green
    exit 0
  }
  Write-Host "mongod was found but did not start. Check $logFile" -ForegroundColor Yellow
  exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "No mongod binary or Docker installation was found." -ForegroundColor Yellow
  Write-Host "Install MongoDB Server, place portable MongoDB under tools\mongodb, or install Docker Desktop." -ForegroundColor Yellow
  exit 1
}

docker compose -f $composeFile up -d
Write-Host "MongoDB is available at mongodb://127.0.0.1:27017" -ForegroundColor Green
Write-Host "Set MONGODB_FALLBACK_ENABLED=true in backend/.env to enable the app fallback." -ForegroundColor Green
