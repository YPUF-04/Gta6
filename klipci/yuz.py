"""Klibi analiz eder: yayıncının kamerası (facecam) nerede, ne kadar hareket var.

Yüz bulma: OpenCV. Varsa YuNet modeli (daha iyi), yoksa OpenCV'nin içindeki Haar.
Facecam ekranda sabit durduğu için, karelerin çoğunda AYNI yerde çıkan yüz = facecam.
Oyundaki karakterlerin yüzleri sürekli yer değiştirir, onlar elenir.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("yuz")
MODEL_YOLU = Path(__file__).resolve().parent.parent / "modeller" / "face_detection_yunet_2023mar.onnx"
MODEL_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
_kilit = threading.Lock()


@dataclass
class Analiz:
    facecam: tuple[float, float, float, float] | None   # (x, y, w, h) 0-1 arası, kaynak görüntüye göre
    aksiyon: float                                        # 0-1: kareler arası ortalama değişim
    kare_w: int = 0
    kare_h: int = 0


def model_indir() -> bool:
    """YuNet yüz modelini indir (230 KB). Başarısızsa Haar ile devam edilir."""
    if MODEL_YOLU.exists():
        return True
    try:
        import httpx
        MODEL_YOLU.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(MODEL_URL, follow_redirects=True, timeout=30)
        r.raise_for_status()
        if len(r.content) < 50_000:
            raise RuntimeError("model dosyası eksik indi")
        MODEL_YOLU.write_bytes(r.content)
        return True
    except Exception as e:  # noqa: BLE001
        log.info("YuNet modeli indirilemedi (%s), Haar kullanılacak", e)
        return False


class _Bulucu:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.yunet = None
        self.haar = None
        if MODEL_YOLU.exists() and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.yunet = cv2.FaceDetectorYN.create(str(MODEL_YOLU), "", (320, 320), 0.75, 0.3, 50)
            except Exception as e:  # noqa: BLE001
                log.info("YuNet açılamadı: %s", e)
        if self.yunet is None and hasattr(cv2, "CascadeClassifier"):
            self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def bul(self, kare) -> list[tuple[int, int, int, int]]:
        h, w = kare.shape[:2]
        if self.yunet is not None:
            self.yunet.setInputSize((w, h))
            _, yuzler = self.yunet.detect(kare)
            return [tuple(int(v) for v in y[:4]) for y in (yuzler if yuzler is not None else [])]
        if self.haar is not None:
            gri = self.cv2.cvtColor(kare, self.cv2.COLOR_BGR2GRAY)
            enk = max(24, h // 22)
            return [tuple(map(int, b)) for b in
                    self.haar.detectMultiScale(gri, 1.1, 6, minSize=(enk, enk))]
        return []


_bulucu: _Bulucu | None = None


def _get() -> _Bulucu:
    global _bulucu
    with _kilit:
        if _bulucu is None:
            _bulucu = _Bulucu()
        return _bulucu


def facecam_sec(kutular: list[list[tuple[int, int, int, int]]], w: int, h: int,
                en_az_oran: float = 0.4) -> tuple[float, float, float, float] | None:
    """Her karedeki yüz kutularından, karelerin çoğunda aynı yerde duranı seç.

    Dönüş: facecam bölgesi (yüzün etrafı genişletilmiş), 0-1 arası (x, y, w, h)."""
    n = len(kutular)
    if n == 0:
        return None
    adaylar: list[list[tuple[int, int, int, int]]] = []
    for kare in kutular:
        for b in kare:
            cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
            for grup in adaylar:
                g = grup[0]
                gx, gy = g[0] + g[2] / 2, g[1] + g[3] / 2
                if abs(cx - gx) < w * 0.05 and abs(cy - gy) < h * 0.07:
                    grup.append(b)
                    break
            else:
                adaylar.append([b])
    # en çok karede görünen grup; eşitse büyük yüz
    adaylar.sort(key=lambda g: (len(g), sum(b[2] for b in g) / len(g)), reverse=True)
    if not adaylar or len(adaylar[0]) < max(2, n * en_az_oran):
        return None
    g = adaylar[0]
    fx = sorted(b[0] + b[2] / 2 for b in g)[len(g) // 2]
    fy = sorted(b[1] + b[3] / 2 for b in g)[len(g) // 2]
    fw = sorted(b[2] for b in g)[len(g) // 2]
    if fw < w * 0.025:   # çok küçük: muhtemelen oyundaki bir yüz
        return None
    # yüzün etrafını kamera kutusu gibi genişlet (omuzlar dahil), 3:2 oranında
    kw = min(w, fw * 3.6)
    kh = min(h, kw / 1.5)
    kx = min(max(0.0, fx - kw / 2), w - kw)
    ky = min(max(0.0, fy - kh * 0.45), h - kh)
    return kx / w, ky / h, kw / w, kh / h


def analiz_et(video: Path, baslangic: float, sure: float, kare_sayisi: int = 14) -> Analiz:
    """Klip boyunca eşit aralıklı kareleri inceler."""
    try:
        import cv2
        import numpy as np
    except Exception as e:  # noqa: BLE001
        log.warning("opencv yok, yüz bulunamıyor: %s", e)
        return Analiz(None, 0.0)
    import subprocess

    from .kayit import _PENCERESIZ, arac
    bul = _get()
    kutular, farklar, onceki = [], [], None
    # kareleri ffmpeg ile çıkar (OpenCV'nin kendi okuyucusu .ts'de yavaş ve gürültülü)
    w, h = 960, 540
    try:
        cik = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vf", f"fps={kare_sayisi / max(sure, 1):.4f},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True, timeout=120, creationflags=_PENCERESIZ).stdout
    except Exception as e:  # noqa: BLE001
        log.warning("kare çıkarılamadı: %s", e)
        return Analiz(None, 0.0)
    boy = w * h * 3
    for i in range(len(cik) // boy):
        kare = np.frombuffer(cik[i * boy:(i + 1) * boy], np.uint8).reshape(h, w, 3)
        kutular.append(bul.bul(kare))
        kucuk = cv2.cvtColor(cv2.resize(kare, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if onceki is not None:
            farklar.append(float(np.mean(np.abs(kucuk - onceki))) / 255.0)
        onceki = kucuk
    fc = facecam_sec(kutular, w, h) if w else None
    aksiyon = min(1.0, (sum(farklar) / len(farklar)) * 6) if farklar else 0.0
    if fc:
        log.info("facecam bulundu: x=%.2f y=%.2f w=%.2f h=%.2f", *fc)
    return Analiz(fc, aksiyon, w, h)
