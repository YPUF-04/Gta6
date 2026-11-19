"""Dikey (9:16) video kurgusu: bulanık arka plan + ortada oyun + üstte başlık
+ ortada büyük altyazı + altta yayıncı adı. Hepsi tek ffmpeg komutu."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .kayit import _PENCERESIZ, arac

W, H = 1080, 1920
CHAT_Y, CHAT_ARALIK = 600, 66   # chat baloncukları oyun görüntüsünün sol üstüne düşer


def chat_sec(mesajlar: list[tuple[float, str, str]], sure: float, satir: int = 3,
             gorunme_sn: float = 2.2, en_sik_sn: float = 0.45) -> list[tuple[float, float, int, str, str]]:
    """Klip boyunca ekrana düşecek chat mesajlarını seç.

    mesajlar: (klibe göre saniye, kullanıcı, mesaj). Kısa ve tepki içeren mesajlar öncelikli,
    aynı anda en fazla `satir` mesaj görünür; yenisi gelince en eskisinin yerine geçer."""
    from .spike import mesaj_puani
    secilen, son_t, sira = [], -99.0, 0
    for t, kim, msg in sorted(mesajlar):
        msg = " ".join(msg.split())
        if not (0 <= t < sure - 0.5) or not msg or "http" in msg or len(msg) > 40:
            continue
        puan, _ = mesaj_puani(msg)
        if t - son_t < (en_sik_sn if puan > 1 else en_sik_sn * 3):
            continue
        son_t = t
        secilen.append((t, min(t + gorunme_sn, sure), sira % satir, kim[:16], msg[:32]))
        sira += 1
    # aynı satıra yeni mesaj gelince eskisi o an kaybolsun (üst üste binmesin)
    for i, (b, e, sl, k, m) in enumerate(secilen):
        sonraki = next((x[0] for x in secilen[i + 1:] if x[2] == sl), None)
        if sonraki is not None and sonraki < e:
            secilen[i] = (b, sonraki, sl, k, m)
    return secilen


def _ass_metin(s: str) -> str:
    return s.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def _zaman(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_yaz(yol: Path, sure: float, baslik: str, kredi: str, imza: str,
            altyazilar: list[tuple[float, float, str]],
            chat: list[tuple[float, float, int, str, str]] | None = None) -> None:
    satirlar = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Başlık: beyaz kutu içinde siyah kalın yazı (viral klip sayfalarının klasiği)
        "Style: Baslik,Arial Black,64,&H00111111,&H00111111,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,250,1",
        # Altyazı: sarı/beyaz kalın, kalın siyah kenar
        "Style: Alt,Arial Black,78,&H00FFFFFF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,470,1",
        "Style: Kredi,Arial,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,230,1",
        # Chat baloncukları: yarı saydam koyu kutu, beyaz yazı
        "Style: Chat,Arial,38,&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,-1,0,0,0,100,100,0,0,3,10,0,7,0,0,0,1",
        "Style: Imza,Arial,34,&H80FFFFFF,&H80FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,170,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    son = _zaman(sure + 1)
    if baslik:
        satirlar.append(f"Dialogue: 2,0:00:00.00,{son},Baslik,,0,0,0,,{{\\fad(150,0)}}{_ass_metin(baslik)}")
    if kredi:
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Kredi,,0,0,0,,{_ass_metin(kredi)}")
    if imza:
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Imza,,0,0,0,,{_ass_metin(imza)}")
    for bas, bit, metin in altyazilar:
        if bit <= 0 or bas >= sure:
            continue
        # küçük "pop" animasyonu
        efekt = "{\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)}"
        satirlar.append(f"Dialogue: 3,{_zaman(bas)},{_zaman(bit)},Alt,,0,0,0,,{efekt}{_ass_metin(metin.upper())}")
    renkler = ["&H00FF9A4B", "&H004BD6FF", "&H0098FF6B", "&H00D37BFF", "&H006B6BFF", "&H00FFE14B"]
    for bas, bit, satir, kim, msg in chat or []:
        y = CHAT_Y + satir * CHAT_ARALIK
        renk = renkler[sum(map(ord, kim)) % len(renkler)]
        efekt = f"{{\\pos(40,{y})\\fad(120,200)}}"
        satirlar.append(f"Dialogue: 4,{_zaman(bas)},{_zaman(bit)},Chat,,0,0,0,,{efekt}"
                        f"{{\\c{renk}&}}{_ass_metin(kim)}: {{\\c&H00FFFFFF&}}{_ass_metin(msg)}")
    yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")


def dikey_video(kaynak: Path, baslangic: float, sure: float, cikti: Path, ass: Path | None,
                zoom: float = 1.3) -> Path:
    zoom = max(1.0, zoom)
    fg = f"crop=iw/{zoom}:ih:(iw-iw/{zoom})/2:0,scale={W}:-2"
    filtre = (
        f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=25:2,eq=brightness=-0.12:saturation=1.2[bg];"
        f"[b]{fg}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v0]"
    )
    if ass is not None:
        filtre += f";[v0]ass={ass.name}[v]"   # cwd=ass klasörü: Windows'ta C:\ kaçış derdi yok
        son = "[v]"
    else:
        son = "[v0]"
    cmd = [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(Path(kaynak).resolve()),
           "-filter_complex", filtre, "-map", son, "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-af", "asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11", "-t", f"{sure:.2f}",
           "-movflags", "+faststart", str(Path(cikti).resolve())]
    subprocess.run(cmd, check=True, cwd=str(ass.parent) if ass else None, creationflags=_PENCERESIZ)
    return cikti


def ses_cikar(kaynak: Path, baslangic: float, sure: float, cikti: Path) -> Path:
    subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(kaynak),
                    "-vn", "-ac", "1", "-ar", "16000", str(cikti)], check=True, creationflags=_PENCERESIZ)
    return cikti
