"""Canlı yayını parça parça (4 sn'lik) diske kaydeder, son birkaç dakikayı tutar.

Chat patladığında geriye dönüp o anı buradan keseriz.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("kayit")
PARCA_SN = 4
_FMT = "%Y%m%d_%H%M%S"
_PENCERESIZ = 0  # alt süreçler aynı konsolu paylaşsın: pencere kapanınca hepsi kapanır


def arac(ad: str) -> str:
    """ffmpeg / ffprobe yolunu bul (PATH veya proje içindeki ffmpeg/bin)."""
    yerel = Path(__file__).resolve().parent.parent / "ffmpeg" / "bin" / (ad + (".exe" if os.name == "nt" else ""))
    if yerel.exists():
        return str(yerel)
    bul = shutil.which(ad)
    if not bul:
        raise RuntimeError(f"{ad} bulunamadı. KURULUM.bat'ı çalıştır.")
    return bul


def parca_zamani(p: Path) -> float:
    return time.mktime(datetime.strptime(p.stem, _FMT).timetuple())


class Kaydedici:
    def __init__(self, url: str, klasor: Path, kalite: str, tampon_sn: int):
        self.url, self.klasor, self.kalite, self.tampon = url, Path(klasor), kalite, tampon_sn
        self._sl: subprocess.Popen | None = None
        self._ff: subprocess.Popen | None = None

    def baslat(self) -> None:
        self.klasor.mkdir(parents=True, exist_ok=True)
        for eski in self.klasor.glob("*.ts"):
            eski.unlink(missing_ok=True)
        sl_cmd = [sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "error",
                  "--twitch-disable-ads", "--hls-live-edge", "2", "--stream-segment-threads", "2",
                  self.url, self.kalite]
        ff_cmd = [arac("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                  "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                  "-f", "segment", "-segment_time", str(PARCA_SN), "-reset_timestamps", "1",
                  "-strftime", "1", str(self.klasor / f"{_FMT}.ts")]
        self._sl = subprocess.Popen(sl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    creationflags=_PENCERESIZ)
        self._ff = subprocess.Popen(ff_cmd, stdin=self._sl.stdout, stderr=subprocess.DEVNULL,
                                    creationflags=_PENCERESIZ)
        self._sl.stdout.close()  # type: ignore[union-attr]
        log.info("kayıt başladı: %s", self.url)

    def calisiyor_mu(self) -> bool:
        return bool(self._sl and self._ff and self._sl.poll() is None and self._ff.poll() is None)

    def durdur(self) -> None:
        for p in (self._sl, self._ff):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(self.klasor, ignore_errors=True)

    def temizle(self) -> None:
        sinir = time.time() - self.tampon
        for p in self.klasor.glob("*.ts"):
            try:
                if parca_zamani(p) < sinir:
                    p.unlink(missing_ok=True)
            except (ValueError, PermissionError):
                pass

    def parcalar(self) -> list[tuple[Path, float]]:
        out = []
        for p in self.klasor.glob("*.ts"):
            try:
                out.append((p, parca_zamani(p)))
            except ValueError:
                pass
        return sorted(out, key=lambda x: x[1])

    def kes(self, bas: float, bit: float, hedef: Path) -> tuple[Path, float] | None:
        """[bas, bit] aralığını kapsayan bitmiş parçaları birleştir.

        Dönüş: (birleşik dosya, dosyanın içinde bas'ın denk geldiği saniye)."""
        tum = self.parcalar()
        if len(tum) < 2:
            return None
        bitmis = tum[:-1]  # sonuncusu hâlâ yazılıyor
        secilen = []
        for i, (p, t) in enumerate(bitmis):
            sonraki = bitmis[i + 1][1] if i + 1 < len(bitmis) else tum[-1][1]
            if sonraki > bas and t < bit:
                secilen.append((p, t))
        if not secilen:
            return None
        hedef.parent.mkdir(parents=True, exist_ok=True)
        liste = hedef.with_suffix(".txt")
        liste.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p, _ in secilen), encoding="utf-8")
        subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", str(hedef)],
                       check=True, creationflags=_PENCERESIZ)
        liste.unlink(missing_ok=True)
        return hedef, max(0.0, bas - secilen[0][1])
