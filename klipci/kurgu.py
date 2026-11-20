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


# Ekran düzenleri:
#  "yuz"  : üstte yayıncının kamerası, altta oyun; konuşma tam ortadaki çizgide kelime kelime (TikTok klip tarzı)
#  "tek"  : ortada oyun, arkası bulanık
#  "tweet": beyaz zemin, üstte tweet gibi sayfa profili + büyük harfli başlık, ortada kare oyun videosu
DUZEN = {
    "yuz": {"kam_h": 680, "alt_pos": (540, 680), "chat_y": 1180, "kredi_mv": 70, "imza_mv": 30},
    "tek": {"kam_h": 0, "baslik": (540, 300), "alt_pos": (540, 1400), "chat_y": 600, "kredi_mv": 230, "imza_mv": 170},
    "tweet": {"video_y": 400, "video_h": 1080, "alt_pos": (540, 1390), "baslik": (540, 560)},
}
MOR = "&H00E43F7B&"   # söylenen kelimenin arkasındaki mor kutu (BGR)


def _altyazi_olaylari(altyazilar, sure: float, x: int, y: int, katman: int = 3) -> list[str]:
    """Kelime zamanı varsa: o an söylenen kelime mor kutulu (CapCut tarzı). Yoksa düz 2-3 kelime."""
    out = []
    for parca in altyazilar:
        bas, bit, metin = parca[0], parca[1], parca[2]
        kelimeler = parca[3] if len(parca) > 3 else None
        if bit <= 0 or bas >= sure or not metin.strip():
            continue
        konum = f"{{\\pos({x},{y})}}"
        if not kelimeler:
            out.append(f"Dialogue: {katman},{_zaman(bas)},{_zaman(bit)},Alt,,0,0,0,,{konum}{_ass_metin(metin)}")
            continue
        for i, (kb, _ke, _k) in enumerate(kelimeler):
            b = bas if i == 0 else kb
            e = kelimeler[i + 1][0] if i + 1 < len(kelimeler) else bit
            if e <= b:
                continue
            yazi = " ".join(
                (f"{{\\3c{MOR}\\bord14\\shad0}}{_ass_metin(w)}{{\\r}}" if j == i else _ass_metin(w))
                for j, (_a, _b, w) in enumerate(kelimeler))
            out.append(f"Dialogue: {katman},{_zaman(b)},{_zaman(e)},Alt,,0,0,0,,{konum}{yazi}")
    return out


def ass_yaz(yol: Path, sure: float, baslik: str, kredi: str, imza: str,
            altyazilar: list[tuple],
            chat: list[tuple[float, float, int, str, str]] | None = None, duzen: str = "tek",
            sayfa: dict | None = None) -> None:
    """sayfa (tweet düzeni için): {"ad": "GTA 6 Anları", "kullanici": "@hesap", "ust": "BAŞLIK", "tik": False}"""
    d = DUZEN.get(duzen, DUZEN["tek"])
    import random
    rnd = random.Random(yol.parent.name)   # her videoda biraz farklı: hepsi aynı şablondan çıkmış gibi durmasın
    alt_font = rnd.choice(["Arial Black", "Arial", "Impact"]) if duzen != "yuz" else rnd.choice(["Arial", "Arial Black"])
    alt_boy = {"yuz": 70, "tek": 74, "tweet": 60}[duzen] + rnd.choice([-4, 0, 4])
    stiller = [
        # Altyazı: beyaz kalın + siyah kenar (söylenen kelime mor kutuda)
        f"Style: Alt,{alt_font},{alt_boy},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,5,40,40,0,1",
        f"Style: Baslik,Arial,{rnd.choice([54, 58, 62])},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,60,60,0,1",
        "Style: Chat,Arial,38,&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,-1,0,0,0,100,100,0,0,3,10,0,7,0,0,0,1",
        f"Style: Kredi,Arial,36,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,{d.get('kredi_mv', 60)},1",
        "Style: ImzaYuz,Arial,34,&H30FFFFFF,&H30FFFFFF,&H90000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,5,40,40,0,1",
        f"Style: Imza,Arial,32,&H80FFFFFF,&H80FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,{d.get('imza_mv', 30)},1",
        # tweet düzeni
        "Style: TAd,Arial,46,&H00141414,&H00141414,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "Style: TKul,Arial,40,&H00727272,&H00727272,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "Style: TUst,Arial Black,38,&H00141414,&H00141414,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,1,0,1,0,0,5,30,30,0,1",
        "Style: TYorum,Arial,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,2,5,60,60,0,1",
        "Style: TKredi,Arial,32,&H00727272,&H00727272,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,1,0,0,5,30,30,0,1",
        "Style: TTik,Arial,40,&H00F09B1D,&H00F09B1D,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "Style: TAvatar,Arial,240,&H00B07A2E,&H00B07A2E,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "Style: THarf,Arial,58,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
    ]
    satirlar = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *stiller, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    son = _zaman(sure + 1)
    ax, ay = d["alt_pos"]

    if duzen == "tweet":
        sp = sayfa or {}
        ad = sp.get("ad") or (imza.lstrip("@") if imza else "GTA 6 Clips")
        kul = sp.get("kullanici") or imza or ""
        if not sp.get("profil"):   # profil fotoğrafı yoksa: renkli daire + baş harf
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},TAvatar,,0,0,0,,{{\\pos(120,212)}}●")
            satirlar.append(f"Dialogue: 2,0:00:00.00,{son},THarf,,0,0,0,,{{\\pos(120,214)}}{_ass_metin(ad[:1].upper())}")
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},TAd,,0,0,0,,{{\\pos(200,170)}}{_ass_metin(ad)}"
                        + (" {\\rTTik}✔" if sp.get("tik") else ""))
        if kul:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},TKul,,0,0,0,,{{\\pos(200,224)}}{_ass_metin(kul)}")
        if sp.get("ust"):
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},TUst,,0,0,0,,{{\\pos(540,340)}}{_ass_metin(sp['ust'].upper())}")
        if baslik:   # videonun üstünde ince beyaz yorum ("suspect is driving" gibi), ilk saniyeler
            bx, by = d["baslik"]
            satirlar.append(f"Dialogue: 5,0:00:00.20,0:00:03.80,TYorum,,0,0,0,,{{\\pos({bx},{by})\\fad(150,250)}}"
                            f"{_ass_metin(baslik)}")
        if kredi:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},TKredi,,0,0,0,,{{\\pos(540,1530)}}{_ass_metin(kredi)}")
        satirlar += _altyazi_olaylari(altyazilar, sure, ax, ay)
        yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
        return

    if baslik and duzen == "tek":
        bx, by = d["baslik"]
        efekt = f"{{\\pos({bx},{by})\\fscx80\\fscy80\\t(0,180,\\fscx100\\fscy100)\\fad(120,0)}}"
        satirlar.append(f"Dialogue: 5,0:00:00.00,{son},Baslik,,0,0,0,,{efekt}{_ass_metin(baslik)}")
    elif baslik and duzen == "yuz" and not altyazilar:
        # konuşma yoksa başlık ilk 3 sn ortadaki çizgide görünsün
        satirlar.append(f"Dialogue: 5,0:00:00.00,0:00:03.00,Baslik,,0,0,0,,{{\\pos({ax},{ay})\\fad(120,200)}}"
                        f"{_ass_metin(baslik)}")
    if kredi:
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Kredi,,0,0,0,,{_ass_metin(kredi)}")
    if imza and duzen == "yuz":
        # kullanıcı adın: üstteki küçük (yüz) ekranın alt ortasında, altyazının hemen üstünde
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},ImzaYuz,,0,0,0,,{{\\pos({W // 2},{d['kam_h'] - 78})}}"
                        f"{_ass_metin(imza)}")
    elif imza:
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Imza,,0,0,0,,{_ass_metin(imza)}")
    satirlar += _altyazi_olaylari(altyazilar, sure, ax, ay)
    renkler = ["&H00FF9A4B", "&H004BD6FF", "&H0098FF6B", "&H00D37BFF", "&H006B6BFF", "&H00FFE14B"]
    for bas, bit, satir, kim, msg in chat or []:
        y = d["chat_y"] + satir * CHAT_ARALIK
        renk = renkler[sum(map(ord, kim)) % len(renkler)]
        efekt = f"{{\\pos(40,{y})\\fad(120,200)}}"
        satirlar.append(f"Dialogue: 4,{_zaman(bas)},{_zaman(bit)},Chat,,0,0,0,,{efekt}"
                        f"{{\\c{renk}&}}{_ass_metin(kim)}: {{\\c&H00FFFFFF&}}{_ass_metin(msg)}")
    yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")


def _yakinlas(genislik: int, yukseklik: int, an: float | None) -> str:
    """Chat'in patladığı anda oyun görüntüsüne ani yakınlaşma (editörlerin 'punch-in'i), 1.4 sn sürer."""
    if an is None or an < 0:
        return ""
    a, b = max(0.0, an - 0.3), an + 1.1
    return (f",zoompan=z='if(between(it\\,{a:.2f}\\,{b:.2f})\\,1.18\\,1)':d=1"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={genislik}x{yukseklik}:fps=30")


def dikey_video(kaynak: Path, baslangic: float, sure: float, cikti: Path, ass: Path | None,
                zoom: float = 1.3, facecam: tuple[float, float, float, float] | None = None,
                an: float | None = None, cubuk: bool = False) -> Path:
    """facecam (0-1 arası x,y,w,h) verilirse: üstte yayıncının kamerası, altta oyun.
    an: klipte chat'in patladığı saniye (o anda kısa yakınlaşma). cubuk: altta ilerleme çubuğu."""
    if facecam:
        fx, fy, fw, fh = facecam
        kh = DUZEN["yuz"]["kam_h"]
        oh = H - kh
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[a]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            f"scale={W}:{kh}:force_original_aspect_ratio=increase,crop={W}:{kh},setsar=1[kam];"
            f"[b]crop=min(iw\\,ih*{W}/{oh}):ih:(iw-min(iw\\,ih*{W}/{oh}))/2:0,"
            f"scale={W}:{oh}:force_original_aspect_ratio=increase,crop={W}:{oh},setsar=1,fps=30"
            f"{_yakinlas(W, oh, an)}[oyun];"
            f"[kam][oyun]vstack=inputs=2,fps=30,format=yuv420p[v0]"
        )
    else:
        zoom = max(1.0, zoom)
        fh = int(round(W * 9 * zoom / 16 / 2)) * 2   # 16:9 kaynak varsayımı
        fg = f"crop=iw/{zoom}:ih:(iw-iw/{zoom})/2:0,scale={W}:{fh},setsar=1,fps=30{_yakinlas(W, fh, an)}"
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=25:2,eq=brightness=-0.12:saturation=1.2[bg];"
            f"[b]{fg}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v0]"
        )
    if cubuk:   # altta ilerleme çubuğu (isteğe bağlı; çoğu insan editör kullanmıyor)
        filtre += (f";color=c=0xFFD400:s={W}x10:r=30:d={sure + 1:.2f}[bar];"
                   f"[v0][bar]overlay=x='-w+w*t/{max(sure, 0.1):.2f}':y=H-10:shortest=1[v1]")
    else:
        filtre += ";[v0]null[v1]"
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


def tweet_video(kaynak: Path, baslangic: float, sure: float, cikti: Path, ass: Path,
                profil: Path | None = None, an: float | None = None) -> Path:
    """Beyaz zemin + tweet tarzı üst kısım + ortada kare oyun videosu."""
    vy, vh = DUZEN["tweet"]["video_y"], DUZEN["tweet"]["video_h"]
    girdiler = ["-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(Path(kaynak).resolve())]
    filtre = (f"color=c=white:s={W}x{H}:r=30:d={sure:.2f}[zemin];"
              f"[0:v]setpts=PTS-STARTPTS,crop=min(iw\\,ih):min(iw\\,ih),scale={W}:{vh},setsar=1,fps=30"
              f"{_yakinlas(W, vh, an)}[oyun];"
              f"[zemin][oyun]overlay=0:{vy}:shortest=1[z1]")
    if profil and Path(profil).exists():
        girdiler += ["-loop", "1", "-i", str(Path(profil).resolve())]
        filtre += (";[1:v]scale=124:124:force_original_aspect_ratio=increase,crop=124:124,format=rgba,"
                   "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-62,Y-62),62),255,0)'[av];"
                   "[z1][av]overlay=58:150:shortest=1[z2]")
        son = "[z2]"
    else:
        son = "[z1]"
    filtre += f";{son}format=yuv420p,ass={ass.name}[v]"
    cmd = [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", *girdiler,
           "-filter_complex", filtre, "-map", "[v]", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "10M", "-bufsize", "20M",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-af", "asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11", "-t", f"{sure:.2f}",
           "-movflags", "+faststart", str(Path(cikti).resolve())]
    subprocess.run(cmd, check=True, cwd=str(ass.parent), creationflags=_PENCERESIZ)
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
