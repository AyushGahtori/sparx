Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$frontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $frontendRoot

python -m http.server 5500
