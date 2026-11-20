@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0klipci\__main__.py" (
  echo.
  echo ##########################################################
  echo  HATA: Bu dosyayi ZIP'in icinden calistirdin
  echo  ya da programin klasoru eksik.
  echo.
  echo  Yapman gereken:
  echo   1. ZIP'i ac, icindekilerin HEPSINI sec ^(Ctrl+A^), kopyala ^(Ctrl+C^)
  echo   2. Programin klasorune ^(ornek C:\GTA6-Klipci^) yapistir ^(Ctrl+V^)
  echo   3. Bu dosyayi O KLASORDEN calistir
  echo ##########################################################
  echo.
  pause
  exit /b 1
)
echo "%~dp0" | find /i "OneDrive" >nul
if not errorlevel 1 echo (Not: klasor OneDrive icinde, program biraz yavas olabilir.)
title GTA 6 Klipci - CALISIYOR (kapatmak icin bu pencereyi kapat veya DURDUR.bat)
if not exist ".venv\Scripts\python.exe" (
  echo Once KURULUM.bat'i calistir!
  pause
  exit /b 1
)
set PATH=%~dp0ffmpeg\bin;%PATH%
set PYTHONUTF8=1
:basla
echo Guncelleme kontrol ediliyor...
".venv\Scripts\python.exe" -m klipci.guncelle --atla=BASLAT.bat
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q --disable-pip-version-check
echo.
echo GTA 6 Klipci basliyor... Klipler Telegram'a gelecek.
echo Bu pencere acik kaldigi surece calisir.
echo.
".venv\Scripts\python.exe" -m klipci
if errorlevel 3 if not errorlevel 4 (
  echo.
  echo Guncelleme icin yeniden baslatiliyor...
  goto basla
)
echo.
echo Program durdu.
pause
