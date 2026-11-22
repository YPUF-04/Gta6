"""Günlük "YAPIŞAN SARKAÇ" videosu: çift kollu sarkaç kaotik sallanır, değdiği her blok ona yapışır.
Sayaç ("N yapıştı"), zamanla değişen renkler, seslendirme (edge-tts), seri numarası. Kendi çizimimiz.
"""
from __future__ import annotations

import asyncio
import colorsys
import logging
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .kayit import _PENCERESIZ, arac
from .merge import FPS, H, W, _tts

log = logging.getLogger("sarkac")
PX, PY = W // 2, 920                 # asılma noktası
L1, L2 = 250.0, 225.0                # kol uzunlukları (px)
BLOK = 32                            # blok kenarı

METIN = {
    "tr": {"baslik": "SARKAÇ #{n}", "ust": "Sarkacın değdiği her blok\\Nona yapışıyor", "sayac": "{n} yapıştı",
           "takip": "DAHA FAZLASI İÇİN TAKİP ET",
           "ses_giris": "Sarkacın değdiği her blok ona yapışıyor!", "ses_cikis": "Daha fazlası için takip et!",
           "sayi": {10: "On!", 25: "Yirmi beş!", 50: "Elli!", 75: "Yetmiş beş!", 100: "Yüz!"},
           "aciklama": "Kaç blok yapışacak sence? 🧲 SARKAÇ #{n} {etiket} #satisfying #physics"},
    "en": {"baslik": "PENDULUM #{n}", "ust": "Every block the pendulum\\Ntouches sticks to it", "sayac": "{n} welded",
           "takip": "FOLLOW FOR MORE",
           "ses_giris": "Every block the pendulum touches sticks to it!", "ses_cikis": "Follow for more!",
           "sayi": {10: "Ten!", 25: "Twenty five!", 50: "Fifty!", 75: "Seventy five!", 100: "One hundred!"},
           "aciklama": "How many will stick? 🧲 PENDULUM #{n} {etiket} #satisfying #physics"},
}


def _renk(t: float, sure: float) -> tuple[int, int, int]:
    """Zamanla gökkuşağı: kırmızı → sarı → yeşil → camgöbeği → mavi → mor (BGR)."""
    h = min(0.82, (t / sure) * 0.82)
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)


def _turev(s, g=1600.0):
    """Çift sarkaç denklemleri (eşit kütleli noktasal kollar). s = [a1, w1, a2, w2]"""
    a1, w1, a2, w2 = s
    d = a1 - a2
    pay = 2 - math.cos(2 * d)
    dw1 = (-g * (2 * math.sin(a1) + math.sin(a1 - 2 * a2)) / L1
           - 2 * math.sin(d) * (w2 * w2 * L2 + w1 * w1 * L1 * math.cos(d)) / L1) / pay
    dw2 = (2 * math.sin(d) * (w1 * w1 * L1 * 2 + g * 2 * math.cos(a1) + w2 * w2 * L2 * math.cos(d))) / (L2 * pay)
    return np.array([w1, dw1, w2, dw2])


def simule(sure: float = 45.0, tohum: int = 0, en_cok: int = 110):
    rnd = np.random.default_rng(tohum)
    s = np.array([rnd.uniform(1.9, 2.6) * rnd.choice([-1, 1]), 0.0, rnd.uniform(2.2, 3.0), 0.0])
    yapisik: list[tuple[int, float, float, tuple]] = []   # (kol 0/1, kol boyunca, dik, renk)
    serbest: list[list] = []                             # [x, y, faz, renk]
    kareler, olaylar = [], []
    dt = 1 / FPS
    esikler = [10, 25, 50, 75, 100]
    sonraki = 0.0
    for k in range(int(sure * FPS)):
        t = k * dt
        for _ in range(8):   # RK4 alt adımlar
            h = dt / 8
            k1 = _turev(s)
            k2 = _turev(s + h / 2 * k1)
            k3 = _turev(s + h / 2 * k2)
            k4 = _turev(s + h * k3)
            s = s + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        a1, a2 = s[0], s[2]
        x1, y1 = PX + L1 * math.sin(a1), PY + L1 * math.cos(a1)
        x2, y2 = x1 + L2 * math.sin(a2), y1 + L2 * math.cos(a2)
        kollar = [((PX, PY), (x1, y1), a1), ((x1, y1), (x2, y2), a2)]
        # yapışık blokların dünya konumları
        dunya = []
        for kol, boy, dik, renk in yapisik:
            (bx, by), _, a = kollar[kol]
            ux, uy = math.sin(a), math.cos(a)         # kol yönü
            nx, ny = uy, -ux                           # dik yön
            dunya.append((bx + ux * boy + nx * dik, by + uy * boy + ny * dik, a, renk))
        # yeni serbest bloklar: sarkacın ulaşabileceği halkada
        erisim = L1 + L2 + 20 + len(yapisik) * 1.2
        if t >= sonraki and len(serbest) < 9 and len(yapisik) < en_cok and t < sure - 4:
            aci, r_ = rnd.uniform(0, 2 * math.pi), rnd.uniform(80, erisim)
            serbest.append([PX + r_ * math.sin(aci), PY + r_ * math.cos(aci), rnd.uniform(0, 6.28), _renk(t, sure)])
            sonraki = t + rnd.uniform(0.15, 0.45)
        # değen yapışsın
        noktalar = [(x1, y1), (x2, y2)] + [(x, y) for x, y, _, _ in dunya]
        kalan = []
        for b in serbest:
            bx, by = b[0] + 6 * math.sin(t * 1.3 + b[2]), b[1] + 6 * math.cos(t * 1.1 + b[2])
            degdi = any(math.hypot(bx - px_, by - py_) < BLOK * 0.95 for px_, py_ in noktalar)
            if not degdi:   # kol çubuklarına değme
                for (ax, ay), (cx, cy), _ in kollar:
                    vx, vy = cx - ax, cy - ay
                    u = max(0.0, min(1.0, ((bx - ax) * vx + (by - ay) * vy) / (vx * vx + vy * vy)))
                    if math.hypot(bx - (ax + u * vx), by - (ay + u * vy)) < BLOK * 0.6:
                        degdi = True
                        break
            if degdi:
                # en yakın kola göre yerel koordinat
                en_iyi = None
                for kol, ((ax, ay), _, a) in enumerate(kollar):
                    ux, uy = math.sin(a), math.cos(a)
                    nx, ny = uy, -ux
                    boy = (bx - ax) * ux + (by - ay) * uy
                    dik = (bx - ax) * nx + (by - ay) * ny
                    m = abs(dik) + max(0, -boy) + max(0, boy - (L1 if kol == 0 else L2))
                    if en_iyi is None or m < en_iyi[0]:
                        en_iyi = (m, kol, boy, dik)
                yapisik.append((en_iyi[1], en_iyi[2], en_iyi[3], b[3]))
                olaylar.append((t, "yapisti", len(yapisik)))
                for e in list(esikler):
                    if len(yapisik) >= e:
                        olaylar.append((t, "esik", e))
                        esikler.remove(e)
            else:
                kalan.append(b)
        serbest = kalan
        kareler.append(((x1, y1), (x2, y2), a1, a2, list(dunya),
                        [(b[0] + 6 * math.sin(t * 1.3 + b[2]), b[1] + 6 * math.cos(t * 1.1 + b[2]), b[3])
                         for b in serbest], len(yapisik)))
    return kareler, olaylar


def _kare(img, x: float, y: float, aci: float, renk) -> None:
    import cv2
    c, s_ = math.cos(-aci), math.sin(-aci)
    y_ = BLOK / 2
    pts = np.array([[x + dx * c - dy * s_, y + dx * s_ + dy * c] for dx, dy in
                    ((-y_, -y_), (y_, -y_), (y_, y_), (-y_, y_))], np.int32)
    cv2.fillPoly(img, [pts], renk, cv2.LINE_AA)


def _ciz(kare) -> np.ndarray:
    import cv2
    (x1, y1), (x2, y2), a1, a2, dunya, serbest, _n = kare
    img = np.full((H, W, 3), (18, 16, 16), np.uint8)
    for x, y, renk in serbest:
        _kare(img, x, y, 0.3, renk)
    for x, y, a, renk in dunya:
        _kare(img, x, y, a, renk)
    cv2.line(img, (PX, PY), (int(x1), int(y1)), (225, 225, 225), 9, cv2.LINE_AA)
    cv2.line(img, (int(x1), int(y1)), (int(x2), int(y2)), (225, 225, 225), 9, cv2.LINE_AA)
    for p in ((PX, PY), (int(x1), int(y1)), (int(x2), int(y2))):
        cv2.circle(img, p, 11, (245, 245, 245), -1, cv2.LINE_AA)
    return img


def _ses(olaylar, sure: float, konusmalar) -> np.ndarray:
    sr = 48000
    ses = np.zeros(int((sure + 1) * sr), np.float32)
    tt = np.arange(int(0.08 * sr)) / sr
    for t, tur, n in olaylar:
        if tur == "yapisti":
            f = 500 + min(n, 110) * 9                      # yapıştıkça ton yükselir
            tik = (np.sin(2 * np.pi * f * tt) * np.exp(-tt * 45)).astype(np.float32) * 0.3
            i = int(t * sr)
            ses[i:i + len(tik)] += tik[:max(0, len(ses) - i)]
    for t, yol in konusmalar:
        try:
            ham = subprocess.run([arac("ffmpeg"), "-v", "error", "-i", str(yol), "-ac", "1", "-ar", str(sr),
                                  "-f", "f32le", "-"], capture_output=True, timeout=30,
                                 creationflags=_PENCERESIZ).stdout
            v = np.frombuffer(ham, np.float32) * 1.1
            i = int(t * sr)
            ses[i:i + len(v)] += v[:max(0, len(ses) - i)]
        except Exception as e:  # noqa: BLE001
            log.debug("seslendirme eklenemedi: %r", e)
    ses = np.tanh(ses * 1.2) * 0.9
    return np.stack([ses, ses], axis=1)


def _ass(yol: Path, dil: str, bolum: int, kareler, sure: float) -> None:
    from .kurgu import _ass_metin, _zaman
    m = METIN[dil]
    s = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
         "MarginR, MarginV, Encoding",
         "Style: Ust,Arial Black,64,&H00E6E6E6,&H00E6E6E6,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,5,40,40,0,1",
         "Style: Sayac,Arial Black,76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,5,40,40,0,1",
         "Style: Etiket,Arial Black,40,&H00FFFFFF,&H00FFFFFF,&H003C1EE6,&H00000000,-1,0,0,0,100,100,0,0,3,10,0,7,0,0,0,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    son = _zaman(sure + 1)
    s.append(f"Dialogue: 2,0:00:00.00,{son},Etiket,,0,0,0,,{{\\pos(40,60)}}{_ass_metin(m['baslik'].format(n=bolum))}")
    s.append(f"Dialogue: 4,0:00:00.00,{_zaman(sure - 3)},Ust,,0,0,0,,{{\\pos(540,300)}}{m['ust']}")
    s.append(f"Dialogue: 6,{_zaman(sure - 3)},{son},Ust,,0,0,0,,{{\\pos(540,300)\\fad(200,0)\\c&H00B45AF0&}}"
             f"{_ass_metin(m['takip'])}")
    onceki, bas = None, 0.0
    for k, kare in enumerate(kareler + [(None,) * 6 + (-1,)]):
        n = kare[6]
        if n != onceki:
            if onceki is not None:
                s.append(f"Dialogue: 3,{_zaman(bas)},{_zaman(k / FPS)},Sayac,,0,0,0,,{{\\pos(540,1560)}}"
                         f"{_ass_metin(m['sayac'].format(n=onceki))}")
            onceki, bas = n, k / FPS
    yol.write_text("\n".join(s) + "\n", encoding="utf-8")


def sarkac_video(cikti: Path, dil: str, bolum: int, tohum: int | None = None, sure: float = 45.0) -> dict:
    from .oyun import OYUN
    if tohum is None:   # bol bloğun yapıştığı, sona kadar dolu dolu giden bir senaryo seç
        en_iyi = None
        for i in range(25):
            kr, ol = simule(sure, bolum * 1000 + i)
            n_ = kr[-1][6]
            if en_iyi is None or n_ > en_iyi[0]:
                en_iyi = (n_, kr, ol)
            if n_ >= 80:
                break
        _, kareler, olaylar = en_iyi
    else:
        kareler, olaylar = simule(sure, tohum)
    m = METIN[dil]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        plan = [(0.3, m["ses_giris"])]
        plan += [(t + 0.05, m["sayi"][n]) for t, tur, n in olaylar if tur == "esik" and n in m["sayi"] and n >= 25]
        plan.append((sure - 2.8, m["ses_cikis"]))
        konusmalar = []
        for i, (t, metin) in enumerate(plan):
            yol = td / f"s{i}.mp3"
            if asyncio.run(_tts(metin, dil, yol)):
                konusmalar.append((t, yol))
        (td / "ses.raw").write_bytes(_ses(olaylar, sure, konusmalar).astype(np.float32).tobytes())
        _ass(td / "yazi.ass", dil, bolum, kareler, sure)
        cikti.parent.mkdir(parents=True, exist_ok=True)
        ff = subprocess.Popen(
            [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-f", "f32le", "-ar", "48000", "-ac", "2", "-i", "ses.raw",
             "-vf", "ass=yazi.ass", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
             str(Path(cikti).resolve())],
            stdin=subprocess.PIPE, cwd=str(td), creationflags=_PENCERESIZ)
        for kare in kareler:
            ff.stdin.write(_ciz(kare).tobytes())
        ff.stdin.close()
        if ff.wait(900) != 0:
            raise RuntimeError("sarkaç videosu kaydedilemedi")
    return {"yol": cikti, "aciklama": m["aciklama"].format(n=bolum, etiket=OYUN.etiket),
            "en_cok": kareler[-1][6], "seslendirme": len(konusmalar)}
