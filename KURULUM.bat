@echo off
chcp 65001 >nul
cd /d "%~dp0"
title GTA 6 Klipci - Kurulum
echo ============================================
echo   GTA 6 KLIPCI - KURULUM (sadece 1 kere)
echo ============================================
echo.

REM ---- Python 3.12 (yeni surumlerde bazi paketler henuz calismiyor) ----
set "PY=py -3.12"
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 goto python_tamam
set "PY=py -3.11"
py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 goto python_tamam

echo [1/5] Python 3.12 kuruluyor (diger Python'una dokunmaz)...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
set "PY=py -3.12"
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 goto python_tamam
echo.
echo Python 3.12 kuruldu ama henuz gorunmuyor.
echo Bu pencereyi kapat ve KURULUM.bat'i TEKRAR calistir.
echo (Yine olmazsa: https://www.python.org/downloads/release/python-3129/
echo  adresinden "Windows installer 64-bit" indirip kur, sonra tekrar dene.)
pause
exit /b 1

:python_tamam
echo [1/5] Python tamam (%PY%).

REM ---- FFmpeg (proje klasorune indirilir) ----
if exist "ffmpeg\bin\ffmpeg.exe" goto ffmpeg_tamam
echo [2/5] FFmpeg indiriliyor (~100 MB) - asagida ilerleme cubugu gorunur...
curl.exe -L --progress-bar --retry 3 -o ffmpeg.zip https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
echo [2/5] FFmpeg aciliyor...
if exist ffmpeg_tmp rmdir /s /q ffmpeg_tmp
mkdir ffmpeg_tmp
tar -xf ffmpeg.zip -C ffmpeg_tmp
powershell -NoProfile -Command "$d = Get-ChildItem ffmpeg_tmp | Select-Object -First 1; Move-Item $d.FullName ffmpeg"
del ffmpeg.zip >nul 2>nul
rmdir /s /q ffmpeg_tmp >nul 2>nul
if exist "ffmpeg\bin\ffmpeg.exe" goto ffmpeg_tamam
echo FFmpeg indirilemedi! Internetini kontrol et ve tekrar dene.
pause
exit /b 1
:ffmpeg_tamam
echo [2/5] FFmpeg tamam.

REM ---- Sanal ortam: yanlis Python surumuyle kurulmussa sil, bastan kur ----
if not exist ".venv\Scripts\python.exe" goto venv_kur
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" >nul 2>nul
if not errorlevel 1 goto venv_tamam
echo [3/5] Eski Python ortami siliniyor (yanlis surum)...
rmdir /s /q .venv
:venv_kur
echo [3/5] Python ortami olusturuluyor...
%PY% -m venv .venv
:venv_tamam

echo.
echo [3/5] Paketler yukleniyor. Her paketin yaninda yuzde ve kalan sure gorunur.
echo       (Satirlar akiyorsa donmamistir, calisiyordur.)
".venv\Scripts\python.exe" -m pip install --upgrade pip --progress-bar on
".venv\Scripts\python.exe" -m pip install -r requirements.txt --progress-bar on
if errorlevel 1 (
  echo.
  echo Paket kurulumu basarisiz oldu. Bu pencerenin ekran goruntusunu at.
  pause
  exit /b 1
)
echo.
echo [3/5] Altyazi paketi yukleniyor (buyuk, biraz surer)...
".venv\Scripts\python.exe" -m pip install -r requirements-altyazi.txt --progress-bar on
if errorlevel 1 (
  echo.
  echo UYARI: Altyazi paketi kurulamadi. Program ALTYAZISIZ calisacak.
  echo Bu pencerenin ekran goruntusunu at, duzeltelim. Kuruluma devam ediliyor...
  echo.
)
where nvidia-smi >nul 2>nul
if errorlevel 1 goto gpu_yok
echo.
echo [3/5] NVIDIA ekran karti bulundu: altyazi hizlandirma paketleri yukleniyor (~1 GB)...
".venv\Scripts\python.exe" -m pip install -r requirements-gpu.txt --progress-bar on
if errorlevel 1 echo UYARI: Hizlandirma kurulamadi, altyazi islemciyle (biraz daha yavas) yapilacak.
:gpu_yok

REM ---- Modeller (onceden indir ki ilk klip beklemesin) ----
if not exist "config.yaml" copy config.example.yaml config.yaml >nul
echo.
echo [4/5] Yapay zeka modelleri indiriliyor (yuzde gorunur)...
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
".venv\Scripts\python.exe" -m klipci.indir

REM ---- Ayar dosyasi ----
echo.
echo [5/5] Ayar dosyasi aciliyor. Telegram bot token'ini yapistir, kaydet, kapat.
echo.
notepad config.yaml
echo.
echo ============================================
echo   KURULUM BITTI!  Artik BASLAT.bat ile ac,
echo   DURDUR.bat ile kapat.
echo ============================================
pause
