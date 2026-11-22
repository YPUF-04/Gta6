"""Günlük "HER SEKME = +1 TOP" videosu: çemberin içinde tek top sekiyor, duvara her çarpışta yeni top doğuyor.
Toplar katlanarak çoğalır (1 → 10 → 100 → 1.000 ...), üstte sayaç, çemberde dönen yaylar, sonda çember taşar.
Seslendirmeli (edge-tts) ve seri numaralı. Tamamen kendi çizimimiz (numpy + OpenCV).
"""
from __future__ import annotations

import asyncio
import logging
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .kayit import _PENCERESIZ, arac
from .merge import FPS, H, W, _tts

log = logging.getLogger("sekme")
CX, CY, R = W // 2, 1000, 470          # çember
TOP_R = 7
RENKLER = np.array([(70, 70, 235), (235, 120, 40), (80, 200, 90), (220, 200, 40), (200, 80, 200),
                    (60, 200, 230)], np.uint8)   # BGR

METIN = {
    "tr": {"baslik": "SEKME #{n}", "ust": "HER SEKME = +1 TOP", "tasti": "TAŞIYOR!", "takip": "DAHA FAZLASI İÇİN TAKİP ET",
           "ses_giris": "Her sekmede bir top daha!", "ses_tasti": "Ve taşıyor!", "ses_cikis": "Daha fazlası için takip et!",
           "sayi": {10: "On!", 100: "Yüz!", 1000: "Bin!", 5000: "Beş bin!"},
           "aciklama": "Kaç topa ulaşacak sence? 😳 SEKME #{n} {etiket} #satisfying #simulation"},
    "en": {"baslik": "BOUNCE #{n}", "ust": "EVERY BOUNCE = +1 BALL", "tasti": "IT'S OVERFLOWING!",
           "takip": "FOLLOW FOR MORE",
           "ses_giris": "Every bounce adds a ball!", "ses_tasti": "And it's overflowing!", "ses_cikis": "Follow for more!",
           "sayi": {10: "Ten!", 100: "One hundred!", 1000: "One thousand!", 5000: "Five thousand!"},
           "aciklama": "Guess how many balls 😳 BOUNCE #{n} {etiket} #satisfying #simulation"},
}


def simule(sure: float = 50.0, tohum: int = 0, sinir: int = 6000):
    """Kare başına (x, y, renk) dizileri, sayaç ve olaylar (zaman, tür, değer)."""
    rnd = np.random.default_rng(tohum)
    a = rnd.uniform(0, 2 * math.pi)
    pos = np.array([[CX, CY - R * 0.4]], np.float64)
    hiz = np.array([[math.cos(a), math.sin(a)]]) * 520.0
    renk = np.array([0], np.int32)
    kareler, olaylar = [], []
    esikler = [10, 100, 1000, 5000]
    tasma = sure - 6.0          # bu andan sonra çember açılır, toplar dışarı dökülür
    dt = 1 / FPS
    # büyüme hızını videonun süresine yay: her sekmede yeni top doğma olasılığı
    p_dogum = 0.3
    tasti = False
    taban = None
    for k in range(int(sure * FPS)):
        t = k * dt
        if not tasti and (t >= tasma or len(pos) >= sinir):
            tasti = True
            olaylar.append((t, "tasti", len(pos)))
        pos += hiz * dt
        if tasti:
            # çember yok: yerçekimiyle ekranın altına dökülüp yığılır (ekran toplarla dolar)
            hiz[:, 1] += 1400 * dt
            if taban is None or len(taban) != len(pos):
                yigin = min(H * 0.62, len(pos) * (2.1 * TOP_R) ** 2 / W)
                taban = (H - 40 - rnd.random(len(pos)) * yigin)
            yere = pos[:, 1] > taban
            pos[yere, 1] = taban[yere]
            hiz[yere] *= (0.5, 0.0)
            kenar = (pos[:, 0] < TOP_R) | (pos[:, 0] > W - TOP_R)
            pos[:, 0] = np.clip(pos[:, 0], TOP_R, W - TOP_R)
            hiz[kenar, 0] *= -0.4
        else:
            d = pos - (CX, CY)
            uz = np.hypot(d[:, 0], d[:, 1])
            carpan = uz > (R - TOP_R)
            if carpan.any():
                n = d[carpan] / uz[carpan, None]
                v = hiz[carpan]
                hiz[carpan] = v - 2 * (v * n).sum(1)[:, None] * n           # yansı
                pos[carpan] = (CX, CY) + n * (R - TOP_R - 1)
                # yeni toplar: çarpan her top bir olasılıkla yeni top doğurur (ilk saniyelerde kesin)
                # hedef eğri: 1 → ~5000 topa (taşma anına kadar) üstel büyüme; olasılık bu eğriyi takip eder
                ilerleme = min(1.0, max(0.0, t - 1.0) / (tasma - 2.0))
                hedef = 5000 ** (ilerleme ** 0.75)   # başta biraz daha hızlı: ilk saniyeler sıkıcı olmasın
                olas = float(np.clip(p_dogum * hedef / len(pos), 0.03, 1.0))
                dogan = np.where(rnd.random(carpan.sum()) < olas)[0]
                if len(dogan) and len(pos) < sinir:
                    dogan = dogan[: sinir - len(pos)]
                    yeni_p = pos[carpan][dogan] - n[dogan] * 6
                    aci = rnd.uniform(0, 2 * math.pi, len(dogan))
                    yeni_v = np.stack([np.cos(aci), np.sin(aci)], 1) * rnd.uniform(380, 620, (len(dogan), 1))
                    pos = np.vstack([pos, yeni_p])
                    hiz = np.vstack([hiz, yeni_v])
                    renk = np.concatenate([renk, rnd.integers(0, len(RENKLER), len(dogan))])
                    olaylar.append((t, "dogum", len(dogan)))
            for e in list(esikler):
                if len(pos) >= e:
                    olaylar.append((t, "esik", e))
                    esikler.remove(e)
        kareler.append((pos.copy(), renk.copy(), len(pos), tasti, t))
    return kareler, olaylar


def _zemin() -> np.ndarray:
    img = np.zeros((H, W, 3), np.uint8)
    yy = np.linspace(0, 1, H)[:, None]
    img[:, :, 0] = (18 + 10 * yy).astype(np.uint8)
    img[:, :, 1] = (14 + 6 * yy).astype(np.uint8)
    img[:, :, 2] = (16 + 6 * yy).astype(np.uint8)
    return img


def _ciz(zemin: np.ndarray, pos, renk, t: float, tasti: bool) -> np.ndarray:
    import cv2
    img = zemin.copy()
    if not tasti:
        # dönen beyaz yaylar (iki yönde)
        for i in range(6):
            aci = (t * 55 * (1 if i % 2 else -1) + i * 60) % 360
            cv2.ellipse(img, (CX, CY), (R - 30 - i * 26, R - 30 - i * 26), 0, aci, aci + 70, (150, 150, 150), 3,
                        cv2.LINE_AA)
        cv2.circle(img, (CX, CY), R + 4, (230, 230, 230), 8, cv2.LINE_AA)
    # toplar: tek tek çizmek yerine maskeyle hızlı çiz
    xs = pos[:, 0].astype(np.int32)
    ys = pos[:, 1].astype(np.int32)
    ic = (xs >= TOP_R) & (xs < W - TOP_R) & (ys >= TOP_R) & (ys < H - TOP_R)
    xs, ys, rk = xs[ic], ys[ic], RENKLER[renk[ic]]
    if len(xs) < 1500:
        for x, y, c in zip(xs, ys, rk):
            cv2.circle(img, (int(x), int(y)), TOP_R, tuple(int(v) for v in c), -1, cv2.LINE_AA)
    else:
        oy, ox = np.mgrid[-TOP_R:TOP_R + 1, -TOP_R:TOP_R + 1]
        disk = (ox ** 2 + oy ** 2) <= TOP_R ** 2
        for dy_, dx_ in zip(oy[disk], ox[disk]):
            img[ys + dy_, xs + dx_] = rk
    return img


def _ses(olaylar, sure: float, konusmalar) -> np.ndarray:
    sr = 48000
    ses = np.zeros(int((sure + 1) * sr), np.float32)
    tt = np.arange(int(0.05 * sr)) / sr
    tik = (np.sin(2 * np.pi * 1400 * tt) * np.exp(-tt * 90)).astype(np.float32) * 0.18
    for t, tur, deger in olaylar:
        if tur == "dogum":
            i = int(t * sr)
            ses[i:i + len(tik)] += tik[:max(0, len(ses) - i)] * min(3.0, 1 + math.log1p(deger) / 2)
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


def _ass(yol: Path, dil: str, bolum: int, kareler, olaylar, sure: float) -> None:
    from .kurgu import _ass_metin, _zaman
    m = METIN[dil]
    s = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
         "MarginR, MarginV, Encoding",
         "Style: Sayac,Arial Black,120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,40,40,0,1",
         "Style: Buyuk,Arial Black,70,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,5,40,40,0,1",
         "Style: Etiket,Arial Black,40,&H00FFFFFF,&H00FFFFFF,&H003C1EE6,&H00000000,-1,0,0,0,100,100,0,0,3,10,0,7,0,0,0,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    son = _zaman(sure + 1)
    s.append(f"Dialogue: 2,0:00:00.00,{son},Etiket,,0,0,0,,{{\\pos(40,60)}}{_ass_metin(m['baslik'].format(n=bolum))}")
    s.append(f"Dialogue: 4,0:00:00.20,0:00:04.00,Buyuk,,0,0,0,,{{\\pos(540,1640)\\fad(150,250)}}{_ass_metin(m['ust'])}")
    for t, tur, deger in olaylar:
        if tur == "tasti":
            s.append(f"Dialogue: 6,{_zaman(t)},{_zaman(min(sure, t + 2.5))},Buyuk,,0,0,0,,{{\\pos(540,1640)"
                     f"\\fscx50\\fscy50\\t(0,180,\\fscx112\\fscy112)\\t(180,280,\\fscx100\\fscy100)\\c&H0066E6FF&}}"
                     f"{_ass_metin(m['tasti'])}")
    s.append(f"Dialogue: 6,{_zaman(sure - 3)},{son},Buyuk,,0,0,0,,{{\\pos(540,1640)\\fad(200,0)\\c&H00B45AF0&}}"
             f"{_ass_metin(m['takip'])}")
    onceki, bas = None, 0.0
    for k, (*_x, n, _tasti, _t) in enumerate(kareler + [(None, None, -1, False, 0)]):
        if n != onceki:
            if onceki is not None:
                s.append(f"Dialogue: 3,{_zaman(bas)},{_zaman(k / FPS)},Sayac,,0,0,0,,{{\\pos(540,330)}}{onceki:,}")
            onceki, bas = n, k / FPS
    yol.write_text("\n".join(s) + "\n", encoding="utf-8")


def sekme_video(cikti: Path, dil: str, bolum: int, tohum: int | None = None, sure: float = 50.0) -> dict:
    from .oyun import OYUN
    tohum = bolum * 104729 if tohum is None else tohum
    kareler, olaylar = simule(sure, tohum)
    m = METIN[dil]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        plan = [(0.3, m["ses_giris"])]
        for t, tur, deger in olaylar:
            if tur == "esik" and deger in m["sayi"]:
                plan.append((t + 0.05, m["sayi"][deger]))
            if tur == "tasti":
                plan.append((t + 0.2, m["ses_tasti"]))
        plan.append((sure - 2.8, m["ses_cikis"]))
        konusmalar = []
        for i, (t, metin) in enumerate(plan):
            yol = td / f"s{i}.mp3"
            if asyncio.run(_tts(metin, dil, yol)):
                konusmalar.append((t, yol))
        (td / "ses.raw").write_bytes(_ses(olaylar, sure, konusmalar).astype(np.float32).tobytes())
        _ass(td / "yazi.ass", dil, bolum, kareler, olaylar, sure)
        cikti.parent.mkdir(parents=True, exist_ok=True)
        ff = subprocess.Popen(
            [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-f", "f32le", "-ar", "48000", "-ac", "2", "-i", "ses.raw",
             "-vf", "ass=yazi.ass", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
             str(Path(cikti).resolve())],
            stdin=subprocess.PIPE, cwd=str(td), creationflags=_PENCERESIZ)
        zemin = _zemin()
        for pos, renk, _n, tasti, t in kareler:
            ff.stdin.write(_ciz(zemin, pos, renk, t, tasti).tobytes())
        ff.stdin.close()
        if ff.wait(900) != 0:
            raise RuntimeError("sekme videosu kaydedilemedi")
    en_cok = max(n for *_x, n, _tasti, _t in kareler)
    return {"yol": cikti, "aciklama": m["aciklama"].format(n=bolum, etiket=OYUN.etiket), "en_cok": en_cok,
            "seslendirme": len(konusmalar)}
