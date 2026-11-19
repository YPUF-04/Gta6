@echo off
chcp 65001 >nul
cd /d "%~dp0"
title GTA 6 Klipci - TEST
if not exist ".venv\Scripts\python.exe" (
  echo Once KURULUM.bat'i calistir!
  pause
  exit /b 1
)
set PATH=%~dp0ffmpeg\bin;%PATH%
set PYTHONUTF8=1
echo ============================================
echo   TEST: Twitch, Kick ve YouTube'da gercek
echo   bir yayina baglanip test klibi yapacak.
echo   Yaklasik 3-4 dakika surer, bekle.
echo   (BASLAT.bat aciksa once onu kapat)
echo ============================================
".venv\Scripts\python.exe" -m klipci.test %*
echo.
pause
