@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Create it first with:
  echo python -m venv .venv
  exit /b 1
)

set APP_PORT_VALUE=8000
for /f "tokens=1,* delims==" %%A in (.env) do (
  if /i "%%A"=="APP_PORT" set APP_PORT_VALUE=%%B
)

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %APP_PORT_VALUE%
