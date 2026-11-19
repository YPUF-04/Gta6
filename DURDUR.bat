@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "klipci.pid" (
  echo Program zaten calismiyor.
  timeout /t 3 >nul
  exit /b
)
set /p PID=<klipci.pid
taskkill /PID %PID% /T /F >nul 2>nul
del klipci.pid >nul 2>nul
echo GTA 6 Klipci durduruldu.
timeout /t 3 >nul
