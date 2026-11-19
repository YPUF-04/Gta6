@echo off
chcp 65001 >nul
cd /d "%~dp0"
title GTA 6 Klipci - CALISIYOR (kapatmak icin bu pencereyi kapat veya DURDUR.bat)
if not exist ".venv\Scripts\python.exe" (
  echo Once KURULUM.bat'i calistir!
  pause
  exit /b 1
)
set PATH=%~dp0ffmpeg\bin;%PATH%
set PYTHONUTF8=1
echo GTA 6 Klipci basliyor... Klipler Telegram'a gelecek.
echo Bu pencere acik kaldigi surece calisir.
echo.
".venv\Scripts\python.exe" -m klipci
echo.
echo Program durdu.
pause
