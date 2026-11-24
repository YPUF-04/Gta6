"""Oyunun kendi konuşmalarını (karakterler, ara sahneler) yayıncının konuşmasından ayırmak — ücretsiz.

GTA gibi oyunlar karakter konuşurken ekranın alt ortasında kendi altyazısını gösterir.
O an ekranda oyun altyazısı varsa, duyulan konuşma büyük ihtimalle oyundandır → bizim altyazıya girmez.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .kayit import _PENCERESIZ, arac

log = logging.getLogger("oyunsesi")
GEN, YUK = 1280, 720
# alt-orta bant (1280x720'ye göre): oyun altyazısının çıktığı yer
BANT_Y = (int(YUK * 0.855), int(YUK * 0.945))
BANT_X = (int(GEN * 0.2), int(GEN * 0.8))


def bant_yazi_var_mi(gri) -> bool:
    """1280x720 gri karede alt-orta bantta ince beyaz yazı var mı?"""
    import cv2
    import numpy as np
    b = gri[BANT_Y[0]:BANT_Y[1], BANT_X[0]:BANT_X[1]]
    th = cv2.morphologyEx(b, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    m = (th > 45) & (b > 170)
    sutun = m.max(axis=0)
    # yazı = yatayda yayılmış ama dikeyde ince bir şerit (tek parlak nesne değil)
    satir = m.max(axis=1)
    return sutun.mean() > 0.06 and satir.mean() < 0.8 and m.sum() > 150


def oyun_altyazi_anlari(video: Path, ofset: float, sure: float, fps: float = 2.0) -> list[tuple[float, bool]]:
    """[(saniye, ekranda oyun altyazısı var mı), ...]"""
    try:
        import numpy as np
        ham = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{ofset:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vf", f"fps={fps},scale={GEN}:{YUK},format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=120, creationflags=_PENCERESIZ).stdout
        n = len(ham) // (GEN * YUK)
        kareler = np.frombuffer(ham[:n * GEN * YUK], np.uint8).reshape(n, YUK, GEN)
        return [(i / fps, bool(bant_yazi_var_mi(k))) for i, k in enumerate(kareler)]
    except Exception as e:  # noqa: BLE001
        log.debug("oyun altyazısı taranamadı: %r", e)
        return []


def oyun_konusmasi_mi(bas: float, bit: float, anlar: list[tuple[float, bool]], oran: float = 0.6) -> bool:
    """Bu konuşma süresince ekranın çoğunda oyun altyazısı varsa: oyundaki karakter konuşuyor."""
    ic = [v for t, v in anlar if bas - 0.3 <= t <= bit + 0.3]
    return bool(ic) and sum(ic) / len(ic) >= oran


def hareketsiz_oran(video: Path, ofset: float, sure: float, facecam=None) -> float:
    """Oyun görüntüsü zamanın ne kadarında neredeyse hiç değişmiyor? (harita, menü, ayarlar, duraklatma)
    facecam (0-1 x,y,w,h) verilirse yayıncının kamerası hesaba katılmaz."""
    try:
        import numpy as np
        w, h = 160, 90
        ham = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{ofset:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vf", f"fps=1,scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=120, creationflags=_PENCERESIZ).stdout
        n = len(ham) // (w * h)
        if n < 4:
            return 0.0
        k = np.frombuffer(ham[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
        maske = np.ones((h, w), bool)
        if facecam:
            fx, fy, fw, fh = facecam
            maske[max(0, int(fy * h) - 2):int((fy + fh) * h) + 2, max(0, int(fx * w) - 2):int((fx + fw) * w) + 2] = False
        farklar = [float(np.mean(np.abs(k[i] - k[i - 1])[maske])) / 255 for i in range(1, n)]
        return sum(1 for d in farklar if d < 0.02) / len(farklar)
    except Exception as e:  # noqa: BLE001
        log.debug("hareket ölçülemedi: %r", e)
        return 0.0


def karanlik_anlar(video: Path, ofset: float, sure: float, facecam=None) -> list[bool]:
    """Her saniye için: oyun görüntüsü kapkara mı? (yükleme ekranı, sahne geçişi, gece ara sahnesi)
    Yayıncının kamerası ve en alttaki altyazı bandı hesaba katılmaz."""
    try:
        import numpy as np
        w, h = 90, 160
        ham = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{ofset:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vf", f"fps=1,scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=120, creationflags=_PENCERESIZ).stdout
        n = len(ham) // (w * h)
        if n < 2:
            return []
        k = np.frombuffer(ham[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
        maske = np.ones((h, w), bool)
        maske[int(h * 0.8):, :] = False            # altyazı bandı
        if facecam:
            fx, fy, fw, fh = facecam
            maske[max(0, int(fy * h) - 2):int((fy + fh) * h) + 2, max(0, int(fx * w) - 2):int((fx + fw) * w) + 2] = False
        sonuc = []
        for kare in k:
            alan = kare[maske]
            sonuc.append(bool(float(alan.mean()) < 35 and float(np.percentile(alan, 95)) < 70))
        return sonuc
    except Exception as e:  # noqa: BLE001
        log.debug("karanlık ölçülemedi: %r", e)
        return []


def karanliktan_kirp(karanlik: list[bool], bas: float, son: float, an: float) -> tuple[float, float]:
    """Klibin başındaki/sonundaki kapkara kısımları (yükleme ekranı, sahne geçişi) at.
    Olaydan sonra 2+ sn süren karanlık başlıyorsa klip orada biter (sahne bitmiştir)."""
    if not karanlik:
        return bas, son
    # sondan: olaydan sonra ilk uzun karanlık
    i = int(max(bas, an + 1))
    while i < min(len(karanlik), int(son)) - 1:
        if karanlik[i] and karanlik[i + 1]:
            son = max(bas + 1, float(i))
            break
        i += 1
    # baştan: olaydan önceki son uzun karanlığın bitişi
    for j in range(int(min(an, son)) - 1, int(bas), -1):
        if 0 <= j < len(karanlik) and karanlik[j] and j - 1 >= 0 and karanlik[j - 1]:
            bas = float(j + 1)
            break
    return bas, son


def yuz_tepkisi(video: Path, ofset: float, sure: float, facecam, an: float) -> float:
    """Yayıncı patlama anında kamerada ne kadar hareketlendi? (normaline göre kat; elleri başında, zıplıyor...)
    Kamera yoksa 0."""
    if not facecam:
        return 0.0
    try:
        import numpy as np
        fx, fy, fw, fh = facecam
        w, h = 96, 96
        ham = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{ofset:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vf", f"fps=2,crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},scale={w}:{h},format=gray",
             "-f", "rawvideo", "-"], capture_output=True, timeout=120, creationflags=_PENCERESIZ).stdout
        n = len(ham) // (w * h)
        if n < 8:
            return 0.0
        k = np.frombuffer(ham[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
        d = np.array([np.mean(np.abs(k[i] - k[i - 1])) for i in range(1, n)])
        a, b = max(0, int((an - 4) * 2)), min(len(d), int((an + 6) * 2))
        if b <= a:
            return 0.0
        normal = float(np.median(d)) + 0.5
        return float(np.percentile(d[a:b], 80)) / normal
    except Exception as e:  # noqa: BLE001
        log.debug("yüz tepkisi ölçülemedi: %r", e)
        return 0.0


def parca_sesi(parca: Path) -> list[float]:
    """Bir kayıt parçasının (4 sn) yarım saniyelik ses şiddetleri (dB). Okunamazsa []."""
    try:
        import numpy as np
        ham = subprocess.run([arac("ffmpeg"), "-v", "error", "-i", str(parca), "-vn", "-ac", "1", "-ar", "8000",
                              "-f", "s16le", "-"], capture_output=True, timeout=20, creationflags=_PENCERESIZ).stdout
        x = np.frombuffer(ham, np.int16).astype(np.float32) / 32768.0
        d = 4000
        return [float(20 * np.log10(np.sqrt(np.mean(x[i:i + d] ** 2)) + 1e-10)) for i in range(0, len(x) - d + 1, d)]
    except Exception:  # noqa: BLE001
        return []


def bagirma_mi(gecmis: list[float], yeni: list[float], fark_db: float = 13.0) -> bool:
    """Yeni parçada ses, yayının son dakikalarının normaline göre aniden çok yükseldi mi? (bağırma/çığlık)"""
    if len(gecmis) < 120 or not yeni:   # en az 1 dk'lık normal öğrenilmeli
        return False
    normal = sorted(gecmis)[len(gecmis) // 2]
    yuksek = sorted(yeni)[-2] if len(yeni) >= 2 else yeni[0]   # tek bir patlama sesi değil, en az 1 sn
    return yuksek >= normal + fark_db and yuksek >= -22


def oyun_aksiyonu(video: Path, ofset: float, sure: float, facecam, an: float) -> float:
    """Patlama anı çevresinde oyun görüntüsü ne kadar sert değişiyor? (kaza, patlama, kovalamaca, ani kamera)
    Klibin normal hareketine göre kat olarak döner; ~1 = sıradan, 2+ = aksiyon."""
    try:
        import numpy as np
        w, h = 160, 90
        ham = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{ofset:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vf", f"fps=4,scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=120, creationflags=_PENCERESIZ).stdout
        n = len(ham) // (w * h)
        if n < 12:
            return 0.0
        k = np.frombuffer(ham[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
        maske = np.ones((h, w), bool)
        if facecam:
            fx, fy, fw, fh = facecam
            maske[max(0, int(fy * h) - 2):int((fy + fh) * h) + 2, max(0, int(fx * w) - 2):int((fx + fw) * w) + 2] = False
        d = np.array([float(np.mean(np.abs(k[i] - k[i - 1])[maske])) for i in range(1, n)])
        a, b = max(0, int((an - 8) * 4)), min(len(d), int((an + 3) * 4))
        if b - a < 4:
            return 0.0
        return float(np.percentile(d[a:b], 90)) / (float(np.median(d)) + 1.0)
    except Exception as e:  # noqa: BLE001
        log.debug("aksiyon ölçülemedi: %r", e)
        return 0.0


def ses_zirvesi(video: Path, ofset: float, sure: float, an: float, once: float = 10.0,
                sonra: float = 2.0) -> tuple[float, float]:
    """Chat'in tepkisinden önceki ~10 sn içinde sesin en çok yükseldiği an (asıl olayın anı: bağırma, patlama,
    çarpma). Dönüş: (klip içi saniye, klibin normaline göre dB farkı). Bulamazsa (an, 0)."""
    try:
        ham = subprocess.run([arac("ffmpeg"), "-v", "error", "-ss", f"{ofset:.2f}", "-t", f"{sure:.2f}",
                              "-i", str(video), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                             capture_output=True, timeout=60, creationflags=_PENCERESIZ).stdout
        import numpy as np
        x = np.frombuffer(ham, np.int16).astype(np.float32) / 32768.0
        d = 2000   # çeyrek saniye
        if len(x) < d * 8:
            return an, 0.0
        db = 20 * np.log10(np.sqrt(np.array([np.mean(x[i:i + d] ** 2) for i in range(0, len(x) - d + 1, d)])) + 1e-10)
        normal = float(np.median(db))
        a, b = max(6, int((an - once) * 4)), min(len(db), int((an + sonra) * 4) + 1)   # klibin ilk 1.5 sn'si değil
        if b - a < 2:
            return an, 0.0
        # tek bir tık değil: yarım saniyelik ortalamanın zirvesi
        yumusak = np.convolve(db, np.ones(2) / 2, mode="same")
        i = a + int(np.argmax(yumusak[a:b]))
        if i in (a, b - 1):   # pencerenin kenarı: gerçek bir zirve değil, sesin genel seviyesi
            return an, 0.0
        return i / 4, float(yumusak[i] - normal)
    except Exception as e:  # noqa: BLE001
        log.debug("ses zirvesi bulunamadı: %r", e)
        return an, 0.0
