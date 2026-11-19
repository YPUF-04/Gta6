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


# Ekran düzenleri. "yuz": üstte yayıncının kamerası, altta oyun. "tek": ortada oyun, arkası bulanık.
DUZEN = {
    "yuz": {"kam_h": 760, "baslik": (540, 760), "chat_y": 800, "alt_mv": 300, "kredi_mv": 150, "imza_mv": 100},
    "tek": {"kam_h": 0, "baslik": (540, 300), "chat_y": 600, "alt_mv": 470, "kredi_mv": 230, "imza_mv": 170},
}


def ass_yaz(yol: Path, sure: float, baslik: str, kredi: str, imza: str,
            altyazilar: list[tuple[float, float, str]],
            chat: list[tuple[float, float, int, str, str]] | None = None, duzen: str = "tek") -> None:
    d = DUZEN.get(duzen, DUZEN["tek"])
    satirlar = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Başlık: telefonla yazılmış gibi sade beyaz kalın yazı + siyah kenar (kutu yok)
        "Style: Baslik,Arial,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,60,60,0,1",
        # Altyazı: beyaz, konuşulan kelime sarı; kalın siyah kenar
        f"Style: Alt,Arial Black,76,&H00FFFFFF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,{d['alt_mv']},1",
        f"Style: Kredi,Arial,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,{d['kredi_mv']},1",
        # Chat baloncukları: yarı saydam koyu kutu, beyaz yazı
        "Style: Chat,Arial,38,&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,-1,0,0,0,100,100,0,0,3,10,0,7,0,0,0,1",
        f"Style: Imza,Arial,34,&H80FFFFFF,&H80FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,{d['imza_mv']},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    son = _zaman(sure + 1)
    if baslik:
        bx, by = d["baslik"]
        # açılışta hafif büyüyerek gelir
        efekt = f"{{\\pos({bx},{by})\\fscx80\\fscy80\\t(0,180,\\fscx100\\fscy100)\\fad(120,0)}}"
        satirlar.append(f"Dialogue: 5,0:00:00.00,{son},Baslik,,0,0,0,,{efekt}{_ass_metin(baslik)}")
    if kredi:
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Kredi,,0,0,0,,{_ass_metin(kredi)}")
    if imza:
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Imza,,0,0,0,,{_ass_metin(imza)}")
    for bas, bit, metin in altyazilar:
        if bit <= 0 or bas >= sure:
            continue
        efekt = "{\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)}"
        satirlar.append(f"Dialogue: 3,{_zaman(bas)},{_zaman(bit)},Alt,,0,0,0,,{efekt}{_ass_metin(metin.upper())}")
    renkler = ["&H00FF9A4B", "&H004BD6FF", "&H0098FF6B", "&H00D37BFF", "&H006B6BFF", "&H00FFE14B"]
    for bas, bit, satir, kim, msg in chat or []:
        y = d["chat_y"] + satir * CHAT_ARALIK
        renk = renkler[sum(map(ord, kim)) % len(renkler)]
        efekt = f"{{\\pos(40,{y})\\fad(120,200)}}"
        satirlar.append(f"Dialogue: 4,{_zaman(bas)},{_zaman(bit)},Chat,,0,0,0,,{efekt}"
                        f"{{\\c{renk}&}}{_ass_metin(kim)}: {{\\c&H00FFFFFF&}}{_ass_metin(msg)}")
    yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")


def dikey_video(kaynak: Path, baslangic: float, sure: float, cikti: Path, ass: Path | None,
                zoom: float = 1.3, facecam: tuple[float, float, float, float] | None = None) -> Path:
    """facecam (0-1 arası x,y,w,h) verilirse: üstte yayıncının kamerası, altta oyun."""
    if facecam:
        fx, fy, fw, fh = facecam
        kh = DUZEN["yuz"]["kam_h"]
        oh = H - kh
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[a]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            f"scale={W}:{kh}:force_original_aspect_ratio=increase,crop={W}:{kh},setsar=1[kam];"
            f"[b]crop=min(iw\\,ih*{W}/{oh}):ih:(iw-min(iw\\,ih*{W}/{oh}))/2:0,"
            f"scale={W}:{oh}:force_original_aspect_ratio=increase,crop={W}:{oh},setsar=1[oyun];"
            f"[kam][oyun]vstack=inputs=2,fps=30,format=yuv420p[v0]"
        )
    else:
        zoom = max(1.0, zoom)
        fg = f"crop=iw/{zoom}:ih:(iw-iw/{zoom})/2:0,scale={W}:-2"
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=25:2,eq=brightness=-0.12:saturation=1.2[bg];"
            f"[b]{fg}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v0]"
        )
    # altta ilerleme çubuğu (izleyici sonuna kadar kalsın diye — reels'lerde yaygın)
    filtre += (f";color=c=0xFFD400:s={W}x10:r=30:d={sure + 1:.2f}[bar];"
               f"[v0][bar]overlay=x='-w+w*t/{max(sure, 0.1):.2f}':y=H-10:shortest=1[v1]")
    if ass is not None:
        filtre += f";[v1]ass={ass.name}[v]"   # cwd=ass klasörü: Windows'ta C:\ kaçış derdi yok
        son = "[v]"
    else:
        son = "[v1]"
    cmd = [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(Path(kaynak).resolve()),
           "-filter_complex", filtre, "-map", son, "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "10M", "-bufsize", "20M",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-af", "asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11", "-t", f"{sure:.2f}",
           "-movflags", "+faststart", str(Path(cikti).resolve())]
    subprocess.run(cmd, check=True, cwd=str(ass.parent) if ass else None, creationflags=_PENCERESIZ)
    return cikti


def video_saglam_mi(yol: Path, en_az_sn: float = 5.0) -> bool:
    """Çıkan videoda görüntü var mı ve yeterince uzun mu? (boş/bozuk klipleri yollamamak için)"""
    try:
        out = subprocess.run([arac("ffprobe"), "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=codec_type:format=duration", "-of", "default=nw=1",
                              str(yol)], capture_output=True, text=True, timeout=30,
                             creationflags=_PENCERESIZ).stdout
    except Exception:  # noqa: BLE001
        return False
    if "codec_type=video" not in out:
        return False
    for satir in out.splitlines():
        if satir.startswith("duration="):
            try:
                return float(satir.split("=", 1)[1]) >= en_az_sn
            except ValueError:
                return False
    return False


def ses_cikar(kaynak: Path, baslangic: float, sure: float, cikti: Path) -> Path:
    subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(kaynak),
                    "-vn", "-ac", "1", "-ar", "16000", str(cikti)], check=True, creationflags=_PENCERESIZ)
    return cikti
