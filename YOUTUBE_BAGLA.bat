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
title GTA 6 Klipci - YOUTUBE BAGLA
if not exist ".venv\Scripts\python.exe" (
  echo Once KURULUM.bat'i calistir!
  pause
  exit /b 1
)
set PATH=%~dp0ffmpeg\bin;%PATH%
set PYTHONUTF8=1
echo ============================================
echo   YOUTUBE KANALINI BAGLA
echo   Tarayici acilacak: kanalini sec, "Izin ver" de.
echo ============================================
set /p HESAP=Hangi hesap? TR ya da EN yaz ve Enter'a bas: 
".venv\Scripts\python.exe" -m klipci.youtube_bagla %HESAP%
echo.
pause
