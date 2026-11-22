"""Günlük "MERGE" videosu: yüzlü toplar bir kaba düşer, aynı boydaki iki top çarpışınca birleşip büyür.
Skor sayacı, "BOSS'U BEKLE!", "SEVİYE 7!", "TAKİP ET" yazıları, pop sesleri ve seslendirme (ücretsiz, edge-tts).

Tamamen kendi çizimimiz: basit fizik + OpenCV ile çizilen yüzlü toplar. Seri numarası her gün artar.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .kayit import _PENCERESIZ, arac

log = logging.getLogger("merge")
W, H, FPS = 1080, 1920, 30
# kabın iç sınırları (piksel)
KL, KR, KUST, KALT = 110, 970, 560, 1560

# seviye: (yarıçap, renk BGR)
SEVIYE = [(30, (90, 200, 255)), (40, (60, 170, 255)), (52, (70, 120, 250)), (66, (90, 90, 235)),
          (82, (150, 80, 220)), (100, (210, 110, 160)), (120, (230, 170, 80)), (144, (120, 210, 90)),
          (172, (60, 220, 230)), (205, (40, 200, 255))]
BOSS = len(SEVIYE) - 1

METIN = {
    "tr": {"bekle": "BOSS'U BEKLE!", "seviye": "SEVİYE {n}!", "boss": "BOSS GELDİ!", "takip": "DAHA FAZLASI İÇİN TAKİP ET",
           "skor": "SKOR", "baslik": "MERGE #{n}",
           "ses_giris": "Boss'u bekle!", "ses_seviye": "Seviye {n}!", "ses_boss": "İşte boss geldi!",
           "ses_cikis": "Daha fazlası için takip et!", "aciklama": "Boss'a kadar izle 😳 MERGE #{n} {etiket} #merge #satisfying"},
    "en": {"bekle": "WAIT FOR THE BOSS!", "seviye": "LEVEL {n}!", "boss": "BOSS UNLOCKED!", "takip": "FOLLOW FOR MORE",
           "skor": "SCORE", "baslik": "MERGE #{n}",
           "ses_giris": "Wait for the boss!", "ses_seviye": "Level {n}!", "ses_boss": "Here comes the boss!",
           "ses_cikis": "Follow for more!", "aciklama": "Wait for the boss 😳 MERGE #{n} {etiket} #merge #satisfying"},
}
SESLER = {"tr": "tr-TR-AhmetNeural", "en": "en-US-AndrewNeural"}


@dataclass
class Top:
    x: float
    y: float
    vx: float
    vy: float
    sv: int
    dogum: float = 0.0   # birleşince küçük "büyüme" animasyonu için

    @property
    def r(self) -> float:
        return SEVIYE[self.sv][0]


def simule(sure: float = 58.0, tohum: int = 0):
    """Fiziği çalıştır; her kare için (toplar, skor) ve olay listesi döndür."""
    rnd = random.Random(tohum)
    toplar: list[Top] = []
    kareler, olaylar = [], []   # olay: (zaman, tür, seviye)
    skor, en_yuksek = 0, 0
    g, alt_adim = 2600.0, 4
    dt = 1 / FPS / alt_adim
    sonraki = 0.4
    for kare in range(int(sure * FPS)):
        t = kare / FPS
        # düşür: başta hızlı, sonra yavaş; çoğunlukla küçük toplar
        if t >= sonraki and t < sure - 3:
            # zamanla daha büyük toplar düşer: boss videonun sonlarına doğru (≈40-52. sn) gelsin
            ilerleme = min(1.0, t / (sure * 0.75))
            agirlik = [max(0.3, 5 - 5 * ilerleme), 4, 2 + 2 * ilerleme, 1 + 3 * ilerleme, 2.5 * ilerleme,
                       1.5 * ilerleme ** 2]
            sv = rnd.choices(range(len(agirlik)), weights=agirlik)[0]
            toplar.append(Top(rnd.uniform(KL + 140, KR - 140), KUST - 260, rnd.uniform(-60, 60), 0, sv, t))
            sonraki = t + (0.3 if t < 20 else 0.38)
        for _ in range(alt_adim):
            for b in toplar:
                b.vy += g * dt
                b.x += b.vx * dt
                b.y += b.vy * dt
                b.vx *= 0.999
            # çarpışma + birleşme
            birlesen: set[int] = set()
            yeni: list[Top] = []
            for i in range(len(toplar)):
                a = toplar[i]
                for j in range(i + 1, len(toplar)):
                    b = toplar[j]
                    dx, dy = b.x - a.x, b.y - a.y
                    d = math.hypot(dx, dy) or 0.01
                    en_az = a.r + b.r
                    if d >= en_az:
                        continue
                    if a.sv == b.sv and a.sv < BOSS and i not in birlesen and j not in birlesen:
                        birlesen |= {i, j}
                        sv = a.sv + 1
                        yeni.append(Top((a.x + b.x) / 2, (a.y + b.y) / 2, (a.vx + b.vx) / 2, -200, sv, t))
                        skor += 10 * (2 ** sv)
                        olaylar.append((t, "birles", sv))
                        if sv > en_yuksek:
                            en_yuksek = sv
                            olaylar.append((t, "yeni_seviye", sv))
                        continue
                    nx, ny = dx / d, dy / d
                    ort = (en_az - d) / 2
                    a.x -= nx * ort
                    a.y -= ny * ort
                    b.x += nx * ort
                    b.y += ny * ort
                    rv = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
                    if rv < 0:
                        j_ = -(1.2) * rv / 2
                        a.vx -= j_ * nx
                        a.vy -= j_ * ny
                        b.vx += j_ * nx
                        b.vy += j_ * ny
            if birlesen:
                toplar = [b for k, b in enumerate(toplar) if k not in birlesen] + yeni
            for b in toplar:   # kap duvarları
                if b.x - b.r < KL:
                    b.x, b.vx = KL + b.r, abs(b.vx) * 0.3
                if b.x + b.r > KR:
                    b.x, b.vx = KR - b.r, -abs(b.vx) * 0.3
                if b.y + b.r > KALT:
                    b.y, b.vy = KALT - b.r, -abs(b.vy) * 0.2
                    b.vx *= 0.96
        # kap taşarsa en üstteki küçük toplar "patlar" (video tıkanmasın)
        if len(toplar) > 46:
            toplar.sort(key=lambda b: (b.sv, b.y))
            toplar = toplar[6:]
        kareler.append(([(b.x, b.y, b.sv, t - b.dogum) for b in toplar], skor))
    return kareler, olaylar


def _top_ciz(img, x: float, y: float, sv: int, yas: float) -> None:
    import cv2
    r, renk = SEVIYE[sv]
    r = int(r * (0.6 + 0.4 * min(1.0, yas / 0.15)))   # yeni doğan top hafifçe büyüyerek gelir
    c = (int(x), int(y))
    cv2.circle(img, c, r, renk, -1, cv2.LINE_AA)
    acik = tuple(min(255, int(k * 1.35)) for k in renk)
    cv2.circle(img, (int(x - r * 0.3), int(y - r * 0.35)), max(2, int(r * 0.28)), acik, -1, cv2.LINE_AA)
    cv2.circle(img, c, r, (30, 30, 30), max(2, r // 18), cv2.LINE_AA)
    # yüz
    gz = max(2, r // 7)
    for s in (-1, 1):
        cv2.circle(img, (int(x + s * r * 0.33), int(y - r * 0.1)), gz, (25, 25, 25), -1, cv2.LINE_AA)
        cv2.circle(img, (int(x + s * r * 0.33 - gz * 0.3), int(y - r * 0.1 - gz * 0.3)), max(1, gz // 3),
                   (255, 255, 255), -1, cv2.LINE_AA)
    cv2.ellipse(img, (int(x), int(y + r * 0.22)), (max(3, int(r * 0.28)), max(2, int(r * 0.16))), 0, 0, 180,
                (25, 25, 25), max(2, r // 16), cv2.LINE_AA)
    if sv >= 5:   # büyükler bıyıklı
        for s in (-1, 1):
            cv2.ellipse(img, (int(x + s * r * 0.17), int(y + r * 0.1)), (int(r * 0.2), int(r * 0.08)),
                        0, 0, 360, (40, 40, 60), -1, cv2.LINE_AA)
    if sv == BOSS:   # boss'a taç
        pts = np.array([[x - r * 0.45, y - r * 0.8], [x - r * 0.45, y - r * 1.15], [x - r * 0.2, y - r * 0.95],
                        [x, y - r * 1.25], [x + r * 0.2, y - r * 0.95], [x + r * 0.45, y - r * 1.15],
                        [x + r * 0.45, y - r * 0.8]], np.int32)
        cv2.fillPoly(img, [pts], (40, 210, 255), cv2.LINE_AA)


def _zemin(seviye: int) -> np.ndarray:
    import cv2
    img = np.zeros((H, W, 3), np.uint8)
    for yy in range(H):   # koyu mor dikey geçiş
        k = yy / H
        img[yy, :] = (int(40 + 30 * k), int(10 + 8 * k), int(25 + 20 * k))
    renk = [(255, 220, 60), (255, 160, 60), (255, 90, 200), (200, 80, 255), (90, 90, 255)][min(4, seviye // 2)]
    # kap: geniş gövde + yuvarlak alt + boyun
    cv2.line(img, (KL - 8, KUST - 120), (KL - 8, KALT - 120), renk, 10, cv2.LINE_AA)
    cv2.line(img, (KR + 8, KUST - 120), (KR + 8, KALT - 120), renk, 10, cv2.LINE_AA)
    cv2.ellipse(img, (W // 2, KALT - 120), ((KR - KL) // 2 + 8, 128), 0, 0, 180, renk, 10, cv2.LINE_AA)
    cv2.line(img, (KL - 8, KUST - 120), (KL + 220, KUST - 300), renk, 10, cv2.LINE_AA)
    cv2.line(img, (KR + 8, KUST - 120), (KR - 220, KUST - 300), renk, 10, cv2.LINE_AA)
    return cv2.GaussianBlur(img, (0, 0), 0.8)


def _ses(olaylar, sure: float, konusmalar: list[tuple[float, Path]]) -> np.ndarray:
    """Pop sesleri (seviyeye göre ton) + seslendirme, 48 kHz stereo float."""
    sr = 48000
    ses = np.zeros(int((sure + 1) * sr), np.float32)
    tt = np.arange(int(0.12 * sr)) / sr
    for t, tur, sv in olaylar:
        if tur != "birles":
            continue
        f = 900 - sv * 60
        pop = (np.sin(2 * np.pi * f * tt * (1 + 2 * tt)) * np.exp(-tt * 38)).astype(np.float32) * 0.35
        i = int(t * sr)
        ses[i:i + len(pop)] += pop[:max(0, len(ses) - i)]
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


async def _tts(metin: str, dil: str, yol: Path) -> bool:
    try:
        import edge_tts
        await edge_tts.Communicate(metin, SESLER.get(dil, SESLER["en"]), rate="+8%").save(str(yol))
        return yol.exists() and yol.stat().st_size > 1000
    except Exception as e:  # noqa: BLE001
        log.warning("seslendirme yapılamadı (internet?): %r", e)
        return False


def _ass(yol: Path, dil: str, bolum: int, kareler, olaylar, sure: float) -> None:
    from .kurgu import _ass_metin, _zaman
    m = METIN[dil]
    s = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
         "MarginR, MarginV, Encoding",
         "Style: Buyuk,Arial Black,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,40,40,0,1",
         "Style: Skor,Arial Black,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,5,40,40,0,1",
         "Style: Etiket,Arial Black,40,&H00FFFFFF,&H00FFFFFF,&H003C1EE6,&H00000000,-1,0,0,0,100,100,0,0,3,10,0,7,0,0,0,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    son = _zaman(sure + 1)
    s.append(f"Dialogue: 2,0:00:00.00,{son},Etiket,,0,0,0,,{{\\pos(40,60)}}{_ass_metin(m['baslik'].format(n=bolum))}")
    s.append(f"Dialogue: 5,0:00:00.20,0:00:03.80,Buyuk,,0,0,0,,{{\\pos(540,330)\\fad(150,250)}}{_ass_metin(m['bekle'])}")
    for t, tur, sv in olaylar:
        if tur == "yeni_seviye" and sv >= 4:
            yazi = m["boss"] if sv == BOSS else m["seviye"].format(n=sv + 1)
            s.append(f"Dialogue: 6,{_zaman(t)},{_zaman(min(sure, t + 1.8))},Buyuk,,0,0,0,,"
                     f"{{\\pos(540,1180)\\fscx50\\fscy50\\t(0,160,\\fscx115\\fscy115)\\t(160,260,\\fscx100\\fscy100)"
                     f"\\fad(0,300)\\c&H0066E6FF&}}{_ass_metin(yazi)}")
    s.append(f"Dialogue: 6,{_zaman(sure - 3)},{son},Buyuk,,0,0,0,,{{\\pos(540,330)\\fad(200,0)\\c&H00B45AF0&}}"
             f"{_ass_metin(m['takip'])}")
    # skor: değiştiği anlarda yeni satır
    onceki, bas = None, 0.0
    for k, (_, skor) in enumerate(kareler + [([], -1)]):
        if skor != onceki:
            if onceki is not None:
                s.append(f"Dialogue: 3,{_zaman(bas)},{_zaman(k / FPS)},Skor,,0,0,0,,{{\\pos(540,1740)}}"
                         f"{m['skor']}: {onceki:,}")
            onceki, bas = skor, k / FPS
    yol.write_text("\n".join(s) + "\n", encoding="utf-8")


def merge_video(cikti: Path, dil: str, bolum: int, tohum: int | None = None, sure: float = 58.0) -> dict:
    """Videoyu üret. Dönüş: {'yol', 'aciklama', 'en_yuksek', 'seslendirme'}"""
    import cv2
    from .oyun import OYUN
    if tohum is None:   # boss'un videonun sonlarına doğru (38-54. sn) geldiği bir senaryo seç
        for i in range(40):
            kareler, olaylar = simule(sure, bolum * 1000 + i)
            boss = [t for t, tur, sv in olaylar if tur == "yeni_seviye" and sv == BOSS]
            if boss and 38 <= boss[0] <= sure - 4:
                break
    else:
        kareler, olaylar = simule(sure, tohum)
    en_yuksek = max((sv for _, tur, sv in olaylar if tur == "yeni_seviye"), default=0)
    m = METIN[dil]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # seslendirme
        konusma_plani = [(0.3, m["ses_giris"])]
        for t, tur, sv in olaylar:
            if tur == "yeni_seviye" and sv >= 5:
                konusma_plani.append((t + 0.1, m["ses_boss"] if sv == BOSS else m["ses_seviye"].format(n=sv + 1)))
        konusma_plani.append((sure - 2.8, m["ses_cikis"]))
        konusmalar = []
        for i, (t, metin) in enumerate(konusma_plani):
            yol = td / f"s{i}.mp3"
            if asyncio.run(_tts(metin, dil, yol)):
                konusmalar.append((t, yol))
        ses = _ses(olaylar, sure, konusmalar)
        wav = td / "ses.raw"
        wav.write_bytes(ses.astype(np.float32).tobytes())
        ass = td / "yazi.ass"
        _ass(ass, dil, bolum, kareler, olaylar, sure)
        cikti.parent.mkdir(parents=True, exist_ok=True)
        ff = subprocess.Popen(
            [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-f", "f32le", "-ar", "48000", "-ac", "2", "-i", str(wav),
             "-vf", f"ass={ass.name}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
             str(Path(cikti).resolve())],
            stdin=subprocess.PIPE, cwd=str(td), creationflags=_PENCERESIZ)
        zeminler: dict[int, np.ndarray] = {}
        en_buyuk = 0
        for toplar, _ in kareler:
            en_buyuk = max([en_buyuk] + [sv for _, _, sv, _ in toplar])
            zemin = zeminler.get(en_buyuk)
            if zemin is None:
                zemin = zeminler[en_buyuk] = _zemin(en_buyuk)
            img = zemin.copy()
            for x, y, sv, yas in sorted(toplar, key=lambda b: b[2]):
                _top_ciz(img, x, y, sv, yas)
            ff.stdin.write(cv2.resize(img, (W, H)).tobytes() if img.shape[:2] != (H, W) else img.tobytes())
        ff.stdin.close()
        if ff.wait(600) != 0:
            raise RuntimeError("merge videosu kaydedilemedi")
    aciklama = m["aciklama"].format(n=bolum, etiket=OYUN.etiket)
    return {"yol": cikti, "aciklama": aciklama, "en_yuksek": en_yuksek + 1, "seslendirme": len(konusmalar)}
