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

    def baslat(self, ilk: bool = True) -> None:
        """ilk=True: temiz başla. ilk=False (yeniden başlatma): eldeki kaydı SİLME, devam et."""
        self.klasor.mkdir(parents=True, exist_ok=True)
        if ilk:
            kilitli = False
            for eski in self.klasor.glob("*.ts"):
                try:
                    eski.unlink(missing_ok=True)
                except OSError:   # başka bir (artık kalmış) işlem kullanıyor
                    kilitli = True
            if kilitli:   # o klasörü bırak, temiz bir klasörde başla
                self.klasor = self.klasor.with_name(f"{self.klasor.name}_{int(time.time())}")
                self.klasor.mkdir(parents=True, exist_ok=True)
                log.info("eski kayıt dosyaları kilitli, yeni klasör kullanılıyor")
        sl_cmd = [sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "error",
                  "--twitch-disable-ads", "--hls-live-edge", "3", "--stream-segment-threads", "2",
                  "--stream-segment-attempts", "5", "--stream-timeout", "90", "--hls-playlist-reload-attempts", "6",
                  self.url, self.kalite]
        ff_cmd = [arac("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                  "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                  "-f", "segment", "-segment_time", str(PARCA_SN), "-reset_timestamps", "1",
                  "-strftime", "1", str(self.klasor / f"{_FMT}.ts")]
        # streamlink'in hata mesajı dosyaya: kayıt neden koptu görülebilsin
        self._hata_yolu = self.klasor.with_name(self.klasor.name + "_hata.txt")
        hata = open(self._hata_yolu, "ab")
        self._sl = subprocess.Popen(sl_cmd, stdout=subprocess.PIPE, stderr=hata, creationflags=_PENCERESIZ)
        self._ff = subprocess.Popen(ff_cmd, stdin=self._sl.stdout, stderr=hata, creationflags=_PENCERESIZ)
        hata.close()
        self._sl.stdout.close()  # type: ignore[union-attr]
        gorunen = self.url.split("?")[0] if "token=" in self.url else self.url
        log.info("kayıt %s: %s", "başladı" if ilk else "devam ediyor", gorunen[:90])

    def son_hata(self) -> str:
        try:
            satirlar = self._hata_yolu.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            return satirlar[-1][:200] if satirlar else ""
        except (OSError, AttributeError):
            return ""

    def calisiyor_mu(self) -> bool:
        return bool(self._sl and self._ff and self._sl.poll() is None and self._ff.poll() is None)

    def _islemleri_kapat(self) -> None:
        for p in (self._sl, self._ff):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()

    def yeniden_baslat(self) -> None:
        """Kopan kaydı yeniden başlat; son dakikaların kaydı korunur (klip kesilebilsin)."""
        self._islemleri_kapat()
        self.baslat(ilk=False)

    def durdur(self) -> None:
        self._islemleri_kapat()
        shutil.rmtree(self.klasor, ignore_errors=True)
        try:
            self._hata_yolu.unlink(missing_ok=True)
        except (OSError, AttributeError):
            pass

    def temizle(self) -> None:
        if not self.klasor.exists():
            return
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
        # bir parça en fazla ne kadar sürer? Yayına göre değişir (Twitch ~4 sn, Kick 6-10 sn): kayıttan ölç
        araliklar = sorted(b[1] - a[1] for a, b in zip(tum, tum[1:]) if b[1] > a[1])
        tipik = araliklar[len(araliklar) // 2] if araliklar else PARCA_SN
        # Kick'te parçalar düzensiz (4-8 sn); gerçek kopma (uyku, internet) 20 sn'den uzun olur
        azami = max(20.0, tipik * 3)
        secilen = []
        for i, (p, t) in enumerate(bitmis):
            bitis = min(tum[i + 1][1], t + azami)
            if bitis > bas and t < bit:
                secilen.append((p, t, bitis))
        if not secilen:
            return None
        # kayıt bu aralığı kesintisiz kapsıyor mu? (bilgisayar uyuduysa / yayın koptuysa eksik olur)
        kesintisiz = all(b[1] - a[1] <= azami for a, b in zip(secilen, secilen[1:]))
        if not kesintisiz or secilen[0][1] > bas + 2 or secilen[-1][2] < bit - 2:
            bosluk = max((b[1] - a[1] for a, b in zip(secilen, secilen[1:])), default=0)
            log.warning("kayıt bu anı tam kapsamıyor, klip atlandı (kayıt %.0f sn sonra başlıyor, "
                        "en büyük boşluk %.0f sn, parça ~%.0f sn) — internet/disk yavaşsa olur",
                        max(0.0, secilen[0][1] - bas), bosluk, tipik)
            return None
        hedef.parent.mkdir(parents=True, exist_ok=True)
        liste = hedef.with_suffix(".txt")
        liste.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p, _, _ in secilen), encoding="utf-8")
        subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", str(hedef)],
                       check=True, creationflags=_PENCERESIZ)
        liste.unlink(missing_ok=True)
        return hedef, max(0.0, bas - secilen[0][1])


def yetim_kayitlari_kapat(tampon_kok: Path) -> int:
    """Önceki çalışmadan kalmış (program kapanınca ölmemiş) ffmpeg kayıtlarını kapat, tamponu temizle."""
    kapatilan = 0
    if os.name == "nt":
        try:
            komut = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
                     "Where-Object { $_.CommandLine -like '*klipci_tampon*' } | "
                     "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", komut], capture_output=True,
                                 text=True, timeout=30, creationflags=_PENCERESIZ).stdout
            kapatilan = len([x for x in out.split() if x.strip().isdigit()])
        except Exception as e:  # noqa: BLE001
            log.debug("yetim kayıt kontrolü olmadı: %r", e)
    if kapatilan:
        log.info("önceki çalışmadan kalan %d kayıt işlemi kapatıldı", kapatilan)
        time.sleep(1)
    shutil.rmtree(tampon_kok, ignore_errors=True)
    return kapatilan
