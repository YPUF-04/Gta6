"""Çıplaklık filtresi: GTA 6'da çıplak karakterler / striptiz kulübü sahneleri var. Bunlar paylaşılırsa
Instagram/Facebook/YouTube videoyu kaldırır, hesap ceza yer. Klip paylaşılmadan önce ayıklanır.

Ücretsiz ve bilgisayarda çalışır: NudeNet (küçük bir ONNX modeli, ~12 MB, ekran kartı gerekmez).
Model yoksa yedek: chat'te ve yayıncının sözünde çıplaklık kelimeleri (birden çok kişi yazıyorsa).
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .kayit import _PENCERESIZ, arac

log = logging.getLogger("ciplak")

# yasak sınıflar (erkek göğsü yok: tişörtsüz yayıncı / karakter sorun değil)
YASAK = {"FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED",
         "BUTTOCKS_EXPOSED", "ANUS_EXPOSED"}
KELIMELER = ("boobs", "boob", "tits", "titties", "naked", "nude", "nudes", "nsfw", "strip club", "stripper",
             "çıplak", "ciplak", "memeler", "göğüs", "striptiz", "kalça", "nipple", "meme gördük")

_dedektor = None
_yok = False


def _model():
    global _dedektor, _yok
    if _dedektor is None and not _yok:
        try:
            from nudenet import NudeDetector
            _dedektor = NudeDetector()
        except Exception as e:  # noqa: BLE001
            _yok = True
            log.warning("çıplaklık modeli yüklenemedi (%r) — sadece chat/söz kelimelerine bakılacak", e)
    return _dedektor


def kelime_isareti(chat: list, segler: list) -> int:
    """Kaç FARKLI kişi (chat) + yayıncının kendisi çıplaklıktan bahsediyor?"""
    kisiler = {k for _, k, m in chat if any(w in (m or "").lower() for w in KELIMELER)}
    soz = any(any(w in (t or "").lower() for w in KELIMELER) for _, _, t in segler)
    return len(kisiler) + (2 if soz else 0)


def kareler(video: Path, ofset: float, sure: float, fps: float = 2.0, en: int = 640):
    import numpy as np
    h = int(en * 9 / 16) // 2 * 2
    ham = subprocess.run(
        [arac("ffmpeg"), "-v", "error", "-ss", f"{ofset:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
         "-vf", f"fps={fps},scale={en}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        capture_output=True, timeout=180, creationflags=_PENCERESIZ).stdout
    n = len(ham) // (en * h * 3)
    return np.frombuffer(ham[:n * en * h * 3], np.uint8).reshape(n, h, en, 3) if n else []


def ciplak_mi(video: Path, ofset: float, sure: float, chat: list | None = None,
              segler: list | None = None) -> tuple[bool, str]:
    """(çıplaklık var mı, açıklama). Emin olunca True: 1 karede çok net (≥0.7) ya da 2+ karede (≥0.45)."""
    d = _model()
    if d is not None:
        try:
            bulunan = []
            for i, k in enumerate(kareler(video, ofset, sure)):
                for x in d.detect(k):
                    if x.get("class") in YASAK and float(x.get("score", 0)) >= 0.45:
                        bulunan.append((i / 2.0, x["class"], float(x["score"])))
            net = [b for b in bulunan if b[2] >= 0.7]
            kare_sayisi = len({round(t, 1) for t, _, _ in bulunan})
            if net or kare_sayisi >= 2:
                t, sinif, skor = max(bulunan, key=lambda b: b[2])
                return True, f"{sinif.lower()} ({t:.0f}. sn, %{int(skor * 100)})"
        except Exception as e:  # noqa: BLE001
            log.debug("çıplaklık kontrolü olmadı: %r", e)
            d = None
    # ek kontrol: model oyun karakterini kaçırabilir; birçok kişi bundan bahsediyorsa riskli say
    n = kelime_isareti(chat or [], segler or [])
    if n >= (4 if d is not None else 3):
        return True, f"chat/yayıncı çıplaklıktan bahsediyor ({n} işaret)"
    return False, ""
