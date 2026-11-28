"""Etkileşimli "Hangisi daha komik? 1 mi 2 mi?" videoları (günlük, seri numaralı).

Günün en iyi iki anı (farklı yayıncılar) art arda gösterilir: 1 → 2, sonunda "Yorumlara yaz: 1 mi 2 mi? 👇".
İzleyici yorum yazar (algoritma için en güçlü sinyallerden), ertesi günün videosu dünün kazananını söyler
(YouTube yorumlarından sayılır). Her şey gerçek yayın görüntüsü: uydurma olay yok.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from .kayit import _PENCERESIZ, arac, sure_olc
from .kurgu import H, W, _ass_metin, _zaman

log = logging.getLogger("duello")

METIN = {
    "tr": {"ust": "HANGİSİ DAHA KOMİK?", "son": "1 mi 2 mi?", "son2": "Yorumlara yaz!"},
    "en": {"ust": "WHICH ONE IS FUNNIER?", "son": "1 or 2?", "son2": "Comment below!"},
}


def oy_say(yorumlar: list[str]) -> tuple[int, int]:
    """Yorumlardaki oylar: '1', '1 😂', 'birinci', 'first' / '2', 'ikinci', 'second'."""
    bir = iki = 0
    for y in yorumlar:
        t = (y or "").strip().lower()
        if re.match(r"^\s*(1|bir|birinci|ilk|first|one|#1)\b", t):
            bir += 1
        elif re.match(r"^\s*(2|iki|ikinci|second|two|#2)\b", t):
            iki += 1
    return bir, iki


def _ass(yol: Path, d1: float, d2: float, son_sn: float, adlar: tuple[str, str], dil: str) -> None:
    m = METIN.get(dil, METIN["en"])
    toplam = d1 + d2 + son_sn
    stil = [
        "Style: Ust,Arial Black,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,6,3,8,40,40,70,1",
        "Style: Rozet,Arial Black,170,&H004BE1FF,&H004BE1FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,9,4,7,0,0,0,1",
        "Style: Ad,Arial Black,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,7,0,0,0,1",
        "Style: Son,Arial Black,120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,8,4,5,40,40,0,1",
        "Style: Son2,Arial Black,64,&H004BE1FF,&H004BE1FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,6,3,5,40,40,0,1",
    ]
    s = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
         "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
         "MarginR, MarginV, Encoding", *stil, "", "[Events]",
         "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
         f"Dialogue: 5,0:00:00.00,{_zaman(d1 + d2)},Ust,,0,0,0,,{_ass_metin(m['ust'])}"]
    for i, (b, e) in enumerate(((0.0, d1), (d1, d1 + d2))):
        giris = "\\fscx40\\fscy40\\t(0,160,\\fscx100\\fscy100)"
        s.append(f"Dialogue: 6,{_zaman(b)},{_zaman(e)},Rozet,,0,0,0,,{{\\pos(40,190){giris}}}{i + 1}")
        if adlar[i]:
            s.append(f"Dialogue: 6,{_zaman(b)},{_zaman(e)},Ad,,0,0,0,,{{\\pos(48,390)}}{_ass_metin(adlar[i])}")
    b = d1 + d2
    s.append(f"Dialogue: 7,{_zaman(b)},{_zaman(toplam + 1)},Son,,0,0,0,,{{\\pos(540,880)\\fscx50\\fscy50"
             f"\\t(0,200,\\fscx100\\fscy100)}}{_ass_metin(m['son'])}")
    s.append(f"Dialogue: 7,{_zaman(b + 0.3)},{_zaman(toplam + 1)},Son2,,0,0,0,,{{\\pos(540,1060)\\fad(150,0)}}"
             f"{_ass_metin(m['son2'])}")
    yol.write_text("\n".join(s) + "\n", encoding="utf-8")


def duello_video(k1: Path, an1: float, k2: Path, an2: float, cikti: Path, dil: str,
                 adlar: tuple[str, str] = ("", ""), parca: float = 10.0, son_sn: float = 2.2) -> Path:
    """İki hazır klipten (dikey, kurgulanmış) olayın çevresindeki ~10'ar sn + son kart."""
    araliklar = []
    for k, an in ((k1, an1), (k2, an2)):
        sure = sure_olc(Path(k)) or parca
        bas = max(0.0, min(an - parca * 0.45, sure - parca))
        araliklar.append((bas, min(parca, sure - bas)))
    (b1, d1), (b2, d2) = araliklar
    ass = Path(cikti).with_suffix(".ass")
    _ass(ass, d1, d2, son_sn, adlar, dil)
    filtre = (
        f"[0:v]trim={b1:.2f}:{b1 + d1:.2f},setpts=PTS-STARTPTS,scale={W}:{H},setsar=1,fps=30[v1];"
        f"[0:a]atrim={b1:.2f}:{b1 + d1:.2f},asetpts=PTS-STARTPTS,aresample=48000,"
        f"afade=t=out:st={d1 - 0.15:.2f}:d=0.15[a1];"
        f"[1:v]trim={b2:.2f}:{b2 + d2:.2f},setpts=PTS-STARTPTS,scale={W}:{H},setsar=1,fps=30,"
        f"fade=t=in:st=0:d=0.15:color=white,tpad=stop_mode=clone:stop_duration={son_sn:.2f}[v2];"
        f"[1:a]atrim={b2:.2f}:{b2 + d2:.2f},asetpts=PTS-STARTPTS,aresample=48000,"
        f"afade=t=out:st={d2 - 0.3:.2f}:d=0.3,apad=pad_dur={son_sn:.2f}[a2];"
        f"[v1][a1][v2][a2]concat=n=2:v=1:a=1[v][a];"
        f"[v]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.62:t=fill:enable='gt(t\\,{d1 + d2:.2f})',"
        f"ass={ass.name},format=yuv420p[vo]"
    )
    try:
        subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(Path(k1).resolve()), "-i", str(Path(k2).resolve()),
                        "-filter_complex", filtre, "-map", "[vo]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-maxrate", "6M", "-bufsize", "12M",
                        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
                        str(Path(cikti).resolve())],
                       check=True, cwd=str(ass.parent), creationflags=_PENCERESIZ, timeout=600)
    finally:
        ass.unlink(missing_ok=True)
    return Path(cikti)
