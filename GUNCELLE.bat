@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0klipci\__main__.py" (
  echo Bu dosyayi programin klasorunden calistir.
  pause
  exit /b 1
)
title GTA 6 Klipci - GUNCELLEME
if not exist ".venv\Scripts\python.exe" (
  echo Once KURULUM.bat'i calistir!
  pause
  exit /b 1
)
set PYTHONUTF8=1
echo En son surum indiriliyor (ayarlarin ve kliplerin korunur)...
".venv\Scripts\python.exe" -m klipci.guncelle --zorla --atla=GUNCELLE.bat
echo.
echo Bitti. Program aciksa kapatip BASLAT.bat ile tekrar ac.
pause
