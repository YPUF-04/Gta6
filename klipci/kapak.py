"""Kapak resmi (thumbnail): klibin en güzel anından bir kare + büyük, okunaklı başlık.

- Kare: patlama anı çevresinde en NET (bulanık olmayan) ve en canlı kare seçilir.
- Üstüne: altta koyu geçiş, iki satırlık büyük beyaz başlık (yayıncının sözü ya da "Yayıncı · GTA 6"),
  küçük "GTA 6" etiketi. 1080x1920 JPG.
Kullanım: YouTube Shorts kapağı (API), Instagram/TikTok'a elle yüklerken kapak olarak seçilir.
"""
from __future__ import annotations

import logging
import subprocess
import textwrap
from pathlib import Path

import numpy as np

from .kayit import _PENCERESIZ, arac

log = logging.getLogger("kapak")
W, H = 1080, 1920


def en_iyi_kare(video: Path, an: float, sure: float):
    """Patlama anı çevresindeki (−2..+3 sn) kareler arasından en net + en canlı olanı (BGR)."""
    import cv2
    bas = max(0.0, an - 2.0)
    bit = min(sure - 0.1, an + 3.0)
    if bit <= bas:
        bas, bit = 0.0, max(0.5, sure - 0.1)
    try:
        ham = subprocess.run([arac("ffmpeg"), "-v", "error", "-ss", f"{bas:.2f}", "-t", f"{bit - bas:.2f}",
                              "-i", str(video), "-vf", f"fps=4,scale={W}:{H}", "-f", "rawvideo",
                              "-pix_fmt", "bgr24", "-"], capture_output=True, timeout=120,
                             creationflags=_PENCERESIZ).stdout
    except Exception as e:  # noqa: BLE001
        log.debug("kare okunamadı: %r", e)
        return None, 0.0
    n = len(ham) // (W * H * 3)
    if not n:
        return None, 0.0
    kareler = np.frombuffer(ham[:n * W * H * 3], np.uint8).reshape(n, H, W, 3)
    en_iyi, en_puan, en_t = None, -1.0, bas
    for i, k in enumerate(kareler):
        gri = cv2.cvtColor(cv2.resize(k, (270, 480)), cv2.COLOR_BGR2GRAY)
        netlik = float(cv2.Laplacian(gri, cv2.CV_64F).var())
        canlilik = float(cv2.cvtColor(cv2.resize(k, (270, 480)), cv2.COLOR_BGR2HSV)[:, :, 1].mean())
        parlak = float(gri.mean())
        puan = netlik * (0.6 + canlilik / 255) * (0.3 if parlak < 35 else 1.0)
        if puan > en_puan:
            en_iyi, en_puan, en_t = k, puan, bas + i / 4
    return (None if en_iyi is None else en_iyi.copy()), en_t


def kapak_yap(video: Path, cikti: Path, baslik: str, an: float, sure: float, etiket: str = "GTA 6",
              dil: str = "en") -> tuple[Path, float] | None:
    """Kapak JPG'si üret. Dönüş: (yol, seçilen karenin saniyesi) — Instagram'a kapak karesi olarak verilir."""
    try:
        import cv2
        from PIL import Image, ImageDraw, ImageFont   # noqa: F401  (varsa daha güzel yazı)
        pil = True
    except Exception:  # noqa: BLE001
        pil = False
    import cv2
    kare, kare_t = en_iyi_kare(video, an, sure)
    if kare is None:
        return None
    img = kare.astype(np.float32)
    # hafif canlandır + alttan koyu geçiş (yazı okunsun)
    img = np.clip((img - 128) * 1.08 + 128 + 4, 0, 255)
    gecis = np.linspace(0, 1, H)[:, None, None]
    # ortadan aşağı koyulaşır: başlık ortada okunur, videodaki altyazı / yazılar geri planda kalır
    golge = np.clip((gecis - 0.35) / 0.4, 0, 1) ** 1.2 * 0.78
    img = (img * (1 - golge)).astype(np.uint8)
    baslik = (baslik or "").strip().strip("“”\"")
    buyuk = baslik.replace("i", "İ").replace("ı", "I").upper() if dil == "tr" else baslik.upper()
    satirlar = textwrap.wrap(buyuk, width=16)[:3] if baslik else []
    if pil:
        img = _yazi_pil(img, satirlar, etiket)
    else:
        img = _yazi_cv2(img, satirlar, etiket)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(cikti), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return cikti, kare_t


def _font(boy: int):
    from PIL import ImageFont
    for ad in ("ariblk.ttf", "Arial Black.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/ariblk.ttf",
               "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(ad, boy)
        except OSError:
            continue
    return ImageFont.load_default()


def _yazi_pil(img: np.ndarray, satirlar: list[str], etiket: str) -> np.ndarray:
    from PIL import Image, ImageDraw
    im = Image.fromarray(img[:, :, ::-1])
    d = ImageDraw.Draw(im)
    boy = 112 if all(len(s) <= 12 for s in satirlar) else 94
    f = _font(boy)
    blok = len(satirlar) * (boy + 16)
    y = int(H * 0.60 - blok / 2)
    # etiket: başlığın hemen üstünde, ortada, mor kutu
    fe = _font(46)
    g = d.textlength(etiket, font=fe)
    ey = y - 100 if satirlar else int(H * 0.60)
    d.rounded_rectangle(((W - g) / 2 - 26, ey, (W + g) / 2 + 26, ey + 72), radius=20, fill=(228, 63, 124)[::-1])
    d.text(((W - g) / 2, ey + 8), etiket, font=fe, fill=(255, 255, 255))
    for s in satirlar:
        g = d.textlength(s, font=f)
        d.text(((W - g) / 2, y), s, font=f, fill=(255, 255, 255), stroke_width=8, stroke_fill=(0, 0, 0))
        y += boy + 16
    return np.array(im)[:, :, ::-1].copy()


def _yazi_cv2(img: np.ndarray, satirlar: list[str], etiket: str) -> np.ndarray:
    import cv2
    y = H - 330 - (len(satirlar) - 1) * 110
    for s in satirlar:
        (g, _), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_DUPLEX, 2.8, 8)
        x = (W - g) // 2
        cv2.putText(img, s, (x, y + 90), cv2.FONT_HERSHEY_DUPLEX, 2.8, (0, 0, 0), 22, cv2.LINE_AA)
        cv2.putText(img, s, (x, y + 90), cv2.FONT_HERSHEY_DUPLEX, 2.8, (255, 255, 255), 8, cv2.LINE_AA)
        y += 110
    cv2.rectangle(img, (44, 120), (290, 190), (228, 63, 124), -1)
    cv2.putText(img, etiket, (66, 172), cv2.FONT_HERSHEY_DUPLEX, 1.5, (255, 255, 255), 3, cv2.LINE_AA)
    return img
