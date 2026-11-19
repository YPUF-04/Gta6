@echo off
chcp 65001 >nul
cd /d "%~dp0"
title GTA 6 Klipci - Kurulum
echo ============================================
echo   GTA 6 KLIPCI - KURULUM (sadece 1 kere)
echo ============================================
echo.

REM ---- Python ----
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [1/4] Python yok, kuruluyor...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo Python kuruldu. Bu pencereyi kapatip KURULUM.bat'i TEKRAR calistir.
    pause
    exit /b
  )
  set PY=python
) else (
  set PY=py -3
)
echo [1/4] Python tamam.

REM ---- FFmpeg (proje klasorune indirilir) ----
if exist "ffmpeg\bin\ffmpeg.exe" (
  echo [2/4] FFmpeg tamam.
) else (
  echo [2/4] FFmpeg indiriliyor ^(~100 MB^)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference='SilentlyContinue';" ^
    "Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile ffmpeg.zip;" ^
    "Expand-Archive ffmpeg.zip -DestinationPath ffmpeg_tmp -Force;" ^
    "$d = Get-ChildItem ffmpeg_tmp | Select-Object -First 1;" ^
    "Move-Item $d.FullName ffmpeg;" ^
    "Remove-Item ffmpeg.zip; Remove-Item ffmpeg_tmp -Recurse -Force"
  if not exist "ffmpeg\bin\ffmpeg.exe" (
    echo FFmpeg indirilemedi! Internetini kontrol et ve tekrar dene.
    pause
    exit /b 1
  )
)

REM ---- Sanal ortam + paketler ----
if not exist ".venv\Scripts\python.exe" (
  echo [3/4] Python ortami olusturuluyor...
  %PY% -m venv .venv
)
echo [3/4] Paketler yukleniyor ^(birkac dakika surebilir^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo Paket kurulumu basarisiz oldu. Yukaridaki hataya bak.
  pause
  exit /b 1
)

REM ---- Ayar dosyasi ----
if not exist "config.yaml" (
  copy config.example.yaml config.yaml >nul
)
echo [4/4] Ayar dosyasi aciliyor. Telegram bot token'ini yapistir, kaydet, kapat.
echo.
notepad config.yaml
echo.
echo ============================================
echo   KURULUM BITTI!  Artik BASLAT.bat ile ac,
echo   DURDUR.bat ile kapat.
echo ============================================
pause
