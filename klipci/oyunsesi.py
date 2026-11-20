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
