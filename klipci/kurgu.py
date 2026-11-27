"""Dikey (9:16) video kurgusu: bulanık arka plan + ortada oyun + üstte başlık
+ ortada büyük altyazı + altta yayıncı adı. Hepsi tek ffmpeg komutu."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .kayit import _PENCERESIZ, arac

log = logging.getLogger("kurgu")

W, H = 1080, 1920
CHAT_Y, CHAT_ARALIK = 600, 52   # chat: oyun görüntüsünün sol alt köşesinde, küçük ve sade


def chat_sec(mesajlar: list[tuple[float, str, str]], sure: float, satir: int = 1,
             gorunme_sn: float = 1.8, en_sik_sn: float = 2.5, en_fazla: int = 5,
             an: float | None = None) -> list[tuple[float, float, int, str, str]]:
    """Ekrana düşecek chat mesajlarını seç — az ve öz.

    Sadece tepki mesajları (LMAO, NO WAY, 💀...), sadece chat'in patladığı anın çevresinde (an-3 .. an+12 sn),
    klip başına en fazla `en_fazla` tane, aynı anda tek satır."""
    from .spike import mesaj_puani
    satir = max(1, min(int(satir), 2))
    adaylar = []
    for t, kim, msg in sorted(mesajlar):
        msg = " ".join(msg.split())
        if not (0 <= t < sure - 0.5) or not msg or "http" in msg or len(msg) > 24:
            continue
        if an is not None and not (an - 3 <= t <= an + 12):
            continue
        if mesaj_puani(msg)[0] <= 1:   # sadece gülme/şok/klip tepkileri
            continue
        adaylar.append((t, kim, msg))
    secilen, son_t, sira = [], -99.0, 0
    for t, kim, msg in adaylar:
        if t - son_t < en_sik_sn or len(secilen) >= en_fazla:
            continue
        son_t = t
        secilen.append((t, min(t + gorunme_sn, sure), sira % satir, kim[:12], msg[:22]))
        sira += 1
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
    "yuz": {"kam_h": 680, "alt_pos": (540, 680), "chat_y": 1420, "kredi_mv": 70, "imza_mv": 30},
    "tek": {"kam_h": 0, "baslik": (540, 300), "alt_pos": (540, 1400), "chat_y": 1236, "kredi_mv": 230, "imza_mv": 170},
    # "pip": oyun tam ekran, yayıncının kamerası sol üstte yuvarlak köşeli küçük kutu (en çok izlenen GTA klip tarzı)
    "pip": {"kam_h": 0, "kutu": (24, 24, 600, 450), "alt_pos": (540, 1640), "chat_y": 1236, "kredi_mv": 0},
    # "pov": yüzsüz oyun anı (bağıran NPC vs.): üstte GTA 6 yazısı, ortada oyun, altında pembe "POV:" yazısı
    # oyun TAM EKRAN (boş yer yok), üstte GTA VI + pembe POV yazısı, altta yayıncının altyazısı
    "pov": {"alt_pos": (540, 1580), "chat_y": 1236, "kredi_mv": 0},
    "tweet": {"video_y": 400, "video_h": 1080, "alt_pos": (540, 1390), "baslik": (540, 560)},
    # "yarim": viral edit tarzı — üst yarı yayıncının yüzü (büyük), ortada beyaz bant + siyah başlık, alt yarı oyun
    "yarim": {"kam_h": 820, "bant_h": 130, "alt_pos": (540, 1600), "chat_y": 1236},
}
MOR = "&H00E43F7B&"   # (eski mor kutu — artık kullanılmıyor)
VURGU = "&H004BE1FF&"  # söylenen kelime: sarı (#FFE14B, ASS'de BGR) — kutu yok, sade ve şık


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
            # yeni cümle hafifçe büyüyerek gelir; söylenen kelime mor kutuda ve biraz büyük
            giris = "\\fscx88\\fscy88\\t(0,110,\\fscx100\\fscy100)" if i == 0 else ""
            yazi = " ".join(
                (f"{{\\c{VURGU}\\fscx110\\fscy110}}{_ass_metin(w)}{{\\r}}" if j == i
                 else _ass_metin(w))
                for j, (_a, _b, w) in enumerate(kelimeler))
            out.append(f"Dialogue: {katman},{_zaman(b)},{_zaman(e)},Alt,,0,0,0,,{{\\pos({x},{y}){giris}}}{yazi}")
    return out


def ass_yaz(yol: Path, sure: float, baslik: str, kredi: str, imza: str,
            altyazilar: list[tuple],
            chat: list[tuple[float, float, int, str, str]] | None = None, duzen: str = "tek",
            sayfa: dict | None = None, tepki: tuple[float, str] | None = None) -> None:
    """sayfa (tweet düzeni için): {"ad": "GTA 6 Anları", "kullanici": "@hesap", "ust": "BAŞLIK", "tik": False}"""
    d = DUZEN.get(duzen, DUZEN["tek"])
    import random
    rnd = random.Random(yol.parent.name)   # her videoda biraz farklı: hepsi aynı şablondan çıkmış gibi durmasın
    alt_font = "Arial Black"   # her videoda aynı, kalın ve okunaklı (tutarlı marka görünümü)
    alt_boy = {"yuz": 70, "tek": 74, "tweet": 60, "pip": 76, "pov": 70, "yarim": 72}[duzen] + rnd.choice([-4, 0, 4])
    stiller = [
        # Altyazı: beyaz kalın + siyah kenar (söylenen kelime mor kutuda)
        # beyaz kalın yazı, ince siyah kenar + yumuşak gölge (kutu yok)
        f"Style: Alt,{alt_font},{alt_boy},&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,1,5,3,5,40,40,0,1",
        f"Style: Baslik,Arial,{rnd.choice([54, 58, 62])},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,60,60,0,1",
        "Style: Chat,Arial,31,&H00FFFFFF,&H00FFFFFF,&H78000000,&H78000000,-1,0,0,0,100,100,0,0,3,7,0,7,0,0,0,1",
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
        "Style: Tepki,Arial Black,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,6,3,5,50,50,0,1",
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
    if tepki and tepki[1]:   # chat patladığı an ekrana düşen makara yazı (büyüyerek gelir, 2.6 sn kalır)
        an, yazi = tepki
        if duzen == "yuz":
            ty = d["kam_h"] + 170
        elif duzen == "pip":
            ty = 760
        elif duzen == "pov":
            ty = 1300
        elif duzen == "tweet":
            ty = DUZEN["tweet"]["video_y"] + 160
        else:
            ty = 470
        b, e = max(0.0, an - 0.2), min(sure, an + 2.6)
        efekt = (f"{{\\pos(540,{ty})\\fscx40\\fscy40\\t(0,140,\\fscx112\\fscy112)"
                 f"\\t(140,240,\\fscx100\\fscy100)\\fad(0,250)}}")
        satirlar.append(f"Dialogue: 6,{_zaman(b)},{_zaman(e)},Tepki,,0,0,0,,{efekt}{_ass_metin(yazi)}")

    if duzen == "tweet":
        sp = sayfa or {}
        ad = sp.get("ad") or (imza.lstrip("@") if imza else "")
        kul = sp.get("kullanici") or imza or ""
        if ad:   # isim girilmediyse profil kısmı hiç çizilmez
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

    if duzen == "pov":
        satirlar.append(f"Dialogue: 2,0:00:00.00,{son},Baslik,,0,0,0,,{{\\pos(540,120)\\fs96\\fnArial Black"
                        f"\\bord7\\3c&H00702A9C&\\shad0}}GTA {{\\c&H00B45AF0&}}VI")
        if baslik:   # pembe POV yazısı, oyunun üstünde, video boyunca
            satirlar.append(f"Dialogue: 5,0:00:00.00,{son},Baslik,,0,0,0,,{{\\pos(540,250)"
                            f"\\fnArial Black\\fs54\\c&H009A40E8&\\bord5\\3c&H00000000&}}{_ass_metin(baslik)}")
        if kredi:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Kredi,,0,0,0,,{{\\an9\\pos({W - 28},30)\\fs26\\alpha&H40&}}"
                            f"{_ass_metin(kredi)}")
        if imza:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},ImzaYuz,,0,0,0,,{{\\pos(540,325)\\fs30}}{_ass_metin(imza)}")
        satirlar += _altyazi_olaylari(altyazilar, sure, ax, ay)
        yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
        return

    if duzen == "yarim":
        kh, bh = d["kam_h"], d["bant_h"]
        if baslik:   # beyaz bantta siyah, kalın başlık (yayıncının gerçek sözü ya da "Yayıncı · GTA 6")
            boy = 58 if len(baslik) <= 24 else 50 if len(baslik) <= 32 else 42
            satirlar.append(f"Dialogue: 5,0:00:00.00,{son},Baslik,,0,0,0,,{{\\pos(540,{kh + bh // 2})"
                            f"\\fnArial Black\\fs{boy}\\c&H00000000&\\bord0\\shad0}}{_ass_metin(baslik)}")
        if kredi:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Kredi,,0,0,0,,{{\\an9\\pos({W - 28},30)\\fs26\\alpha&H40&}}"
                            f"{_ass_metin(kredi)}")
        if imza:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},ImzaYuz,,0,0,0,,{{\\pos({W // 2},{kh - 40})\\fs30}}"
                            f"{_ass_metin(imza)}")
        satirlar += _altyazi_olaylari(altyazilar, sure, ax, ay)
        yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
        return

    if duzen == "pip":
        # sade: başlık / chat yazısı yok. Kaynak sağ üstte minik, kullanıcı adın kamera kutusunun alt ortasında
        kx, ky, kw, kh = d["kutu"]
        if kredi:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Kredi,,0,0,0,,{{\\an9\\pos({W - 28},30)\\fs26\\alpha&H40&}}"
                            f"{_ass_metin(kredi)}")
        if imza:
            satirlar.append(f"Dialogue: 1,0:00:00.00,{son},ImzaYuz,,0,0,0,,{{\\pos({kx + kw // 2},{ky + kh - 30})\\fs30}}"
                            f"{_ass_metin(imza)}")
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
    if kredi and duzen == "yuz":
        satirlar.append(f"Dialogue: 1,0:00:00.00,{son},Kredi,,0,0,0,,{{\\an7\\pos(28,24)\\fs28\\alpha&H30&}}"
                        f"{_ass_metin(kredi)}")
    elif kredi:
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


# görüntü: biraz daha canlı renk + kontrast, hafif netleştirme (720p yayın 1080'e büyütülünce yumuşamasın)
GRADE = ",eq=contrast=1.06:saturation=1.14:gamma=0.98,unsharp=5:5:0.5:5:5:0"


def _yakinlas(genislik: int, yukseklik: int, an: float | None, sure: float | None = None) -> str:
    """Sinematik hareket: klip boyunca çok yavaş yakınlaşma + chat'in patladığı an yumuşak bir 'punch-in'
    (sert sıçrama değil; ~0.5 sn'de girip çıkar). Kare kare ölçeklenir, zoompan titremesi yok."""
    drift = f"0.045*t/{max(sure, 1.0):.2f}" if sure else "0"
    punch = f"+0.13*exp(-pow((t-{an:.2f})/0.45\\,2))" if (an is not None and an >= 0) else ""
    if not sure and not punch:
        return ""
    z = f"(1+{drift}{punch})"
    return (f",scale=w='2*trunc({genislik}*{z}/2)':h='2*trunc({yukseklik}*{z}/2)':eval=frame:flags=bicubic,"
            f"crop={genislik}:{yukseklik}:(iw-{genislik})/2:(ih-{yukseklik})/2")


def dikey_video(kaynak: Path, baslangic: float, sure: float, cikti: Path, ass: Path | None,
                zoom: float = 1.3, facecam: tuple[float, float, float, float] | None = None,
                an: float | None = None, cubuk: bool = False, duzen: str = "yuz", dram: bool = False) -> Path:
    """dram: olayın anında "dramatik" geçiş — görüntü siyah-beyaza döner ve alttan uğursuz, uzayan bir ton
    girer (viral "olaylar kötüye gidiyor" editleri gibi). Müzik telifli değil: ses burada üretilir.
    facecam (0-1 arası x,y,w,h) verilirse: üstte yayıncının kamerası, altta oyun.
    an: klipte chat'in patladığı saniye (o anda kısa yakınlaşma). cubuk: altta ilerleme çubuğu."""
    if duzen == "pov":   # oyun tam ekran, kamera yok
        filtre = (f"[0:v]setpts=PTS-STARTPTS,crop=min(iw\\,ih*{W}/{H}):ih:(iw-min(iw\\,ih*{W}/{H}))/2:0,"
                  f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,fps=30"
                  f"{GRADE}{_yakinlas(W, H, an, sure)},format=yuv420p[v0]")
    elif facecam and duzen == "pip":
        fx, fy, fw, fh = facecam
        kx, ky, kw, kh = DUZEN["pip"]["kutu"]
        cer = 5    # kamera kutusunun beyaz çerçevesi (px)
        r = 32     # köşe yuvarlaklığı
        kose = (f"if(gt(abs(X-W/2),W/2-{r})*gt(abs(Y-H/2),H/2-{r}),"
                f"if(lte(hypot({r}-(W/2-abs(X-W/2)),{r}-(H/2-abs(Y-H/2))),{r}),255,0),255)")
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[b]crop=min(iw\\,ih*{W}/{H}):ih:(iw-min(iw\\,ih*{W}/{H}))/2:0,"
            f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,fps=30"
            f"{GRADE}{_yakinlas(W, H, an, sure)}[oyun];"
            f"[a]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            f"scale={kw}:{kh}:force_original_aspect_ratio=increase:flags=lanczos,crop={kw}:{kh},setsar=1,fps=30"
            f"{GRADE},pad={kw + 2 * cer}:{kh + 2 * cer}:{cer}:{cer}:color=white,"
            f"format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='{kose}'[kam];"
            f"[oyun][kam]overlay={kx - cer}:{ky - cer},fps=30,format=yuv420p[v0]"
        )
        cubuk = True   # bu tarzda altta ince ilerleme çubuğu var
    elif facecam and duzen == "yarim":
        fx, fy, fw, fh = facecam
        kh, bh = DUZEN["yarim"]["kam_h"], DUZEN["yarim"]["bant_h"]
        oh = H - kh - bh
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[a]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            f"scale={W}:{kh}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{kh},setsar=1,fps=30"
            f"{GRADE}[kam];"
            f"color=c=white:s={W}x{bh}:r=30:d={sure + 1:.2f},setsar=1[bant];"
            f"[b]crop=min(iw\\,ih*{W}/{oh}):ih:(iw-min(iw\\,ih*{W}/{oh}))/2:0,"
            f"scale={W}:{oh}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{oh},setsar=1,fps=30"
            f"{GRADE}{_yakinlas(W, oh, an, sure)}[oyun];"
            f"[kam][bant][oyun]vstack=inputs=3:shortest=1,fps=30,format=yuv420p[v0]"
        )
    elif facecam:
        fx, fy, fw, fh = facecam
        kh = DUZEN["yuz"]["kam_h"]
        oh = H - kh
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[a]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            f"scale={W}:{kh}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{kh},setsar=1{GRADE}[kam];"
            f"[b]crop=min(iw\\,ih*{W}/{oh}):ih:(iw-min(iw\\,ih*{W}/{oh}))/2:0,"
            f"scale={W}:{oh}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{oh},setsar=1,fps=30"
            f"{GRADE}{_yakinlas(W, oh, an, sure)}[oyun];"
            f"[kam][oyun]vstack=inputs=2,fps=30,format=yuv420p[v0]"
        )
    else:
        zoom = max(1.0, zoom)
        fh = int(round(W * 9 * zoom / 16 / 2)) * 2   # 16:9 kaynak varsayımı
        fg = (f"crop=iw/{zoom}:ih:(iw-iw/{zoom})/2:0,scale={W}:{fh}:flags=lanczos,setsar=1,fps=30"
              f"{GRADE}{_yakinlas(W, fh, an, sure)}")
        filtre = (
            f"[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=25:2,eq=brightness=-0.12:saturation=1.2[bg];"
            f"[b]{fg}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v0]"
        )
    if cubuk:   # altta ilerleme çubuğu (isteğe bağlı; çoğu insan editör kullanmıyor)
        renk, kalin = ("0xE8283C", 8) if duzen == "pip" else ("0xFFD400", 10)
        filtre += (f";color=c={renk}:s={W}x{kalin}:r=30:d={sure + 1:.2f}[bar];"
                   f"[v0][bar]overlay=x='-w+w*t/{max(sure, 0.1):.2f}':y=H-{kalin}:shortest=1[v1]")
    else:
        filtre += ";[v0]null[v1]"
    dram = bool(dram and an is not None and 1.0 <= an <= sure - 2.0)
    if dram:
        a0 = an + 0.15
        # görüntü: olaydan hemen sonra ~0.3 sn içinde renk çekilir, siyah-beyaz kalır
        filtre += (f";[v1]hue=s='if(lt(t\\,{a0:.2f})\\,1\\,max(0\\,1-(t-{a0:.2f})*3.5))'[v1d]")
        vgir = "[v1d]"
    else:
        vgir = "[v1]"
    if ass is not None:
        filtre += (f";{vgir}ass={ass.name},fade=t=out:st={max(0.0, sure - 0.3):.2f}:d=0.3[v]")   # cwd=ass klasörü
        son = "[v]"
    else:
        son = vgir
    ses_son = f"afade=t=in:d=0.05,afade=t=out:st={max(0.0, sure - 0.35):.2f}:d=0.35"
    if dram:
        a0 = an + 0.15
        # uğursuz ton: 220 Hz (+110 / 330 Hz) hafif titreşimli, olayda 0.25 sn'de girer, sona kadar sürer
        filtre += (
            f";[0:a]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,"
            f"loudnorm=I=-15:TP=-2:LRA=11,"
            f"volume='if(lt(t\\,{a0:.2f})\\,1\\,0.8)':eval=frame[oa];"
            f"aevalsrc='(0.16*sin(2*PI*220*t)+0.09*sin(2*PI*110*t)+0.05*sin(2*PI*330*t))"
            f"*(0.8+0.2*sin(2*PI*4.5*t))':s=48000:c=stereo:d={sure + 0.5:.2f},"
            f"volume='if(lt(t\\,{a0:.2f})\\,0\\,min(1\\,(t-{a0:.2f})/0.25))':eval=frame[ton];"
            f"[oa][ton]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.9,{ses_son}[ao]")
        ses_harita, ses_af = "[ao]", []
    else:
        ses_harita = "0:a:0?"
        ses_af = ["-af", f"asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11,{ses_son}"]
    cmd = [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(Path(kaynak).resolve()),
           "-filter_complex", filtre, "-map", son, "-map", ses_harita,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-maxrate", "6M", "-bufsize", "12M",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
           *ses_af, "-t", f"{sure:.2f}",
           "-movflags", "+faststart", str(Path(cikti).resolve())]
    subprocess.run(cmd, check=True, cwd=str(ass.parent) if ass else None, creationflags=_PENCERESIZ)
    return cikti


def tweet_video(kaynak: Path, baslangic: float, sure: float, cikti: Path, ass: Path,
                profil: Path | None = None, an: float | None = None) -> Path:
    """Beyaz zemin + tweet tarzı üst kısım + ortada kare oyun videosu."""
    vy, vh = DUZEN["tweet"]["video_y"], DUZEN["tweet"]["video_h"]
    girdiler = ["-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(Path(kaynak).resolve())]
    filtre = (f"color=c=white:s={W}x{H}:r=30:d={sure:.2f}[zemin];"
              f"[0:v]setpts=PTS-STARTPTS,crop=min(iw\\,ih):min(iw\\,ih),scale={W}:{vh}:flags=lanczos,setsar=1,fps=30"
              f"{GRADE}{_yakinlas(W, vh, an, sure)}[oyun];"
              f"[zemin][oyun]overlay=0:{vy}:shortest=1[z1]")
    if profil and Path(profil).exists():
        girdiler += ["-loop", "1", "-i", str(Path(profil).resolve())]
        filtre += (";[1:v]scale=124:124:force_original_aspect_ratio=increase,crop=124:124,format=rgba,"
                   "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-62,Y-62),62),255,0)'[av];"
                   "[z1][av]overlay=58:150:shortest=1[z2]")
        son = "[z2]"
    else:
        son = "[z1]"
    filtre += f";{son}format=yuv420p,ass={ass.name},fade=t=out:st={max(0.0, sure - 0.3):.2f}:d=0.3[v]"
    cmd = [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", *girdiler,
           "-filter_complex", filtre, "-map", "[v]", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-maxrate", "6M", "-bufsize", "12M",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
           "-af", f"asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.05,"
                  f"afade=t=out:st={max(0.0, sure - 0.35):.2f}:d=0.35", "-t", f"{sure:.2f}",
           "-movflags", "+faststart", str(Path(cikti).resolve())]
    subprocess.run(cmd, check=True, cwd=str(ass.parent), creationflags=_PENCERESIZ)
    return cikti


def video_saglam_mi(yol: Path, en_az_sn: float = 5.0, ses_gerekli: bool = True) -> bool:
    """Çıkan video gerçekten dolu mu? (görüntü uzunluğu + ses + düz beyaz/siyah değil)"""
    from .kayit import sure_olc
    v = sure_olc(yol, "v:0")
    if v < en_az_sn:
        return False
    if ses_gerekli and sure_olc(yol, "a:0") < v * 0.5:
        return False
    # görüntünün ortası tek renk mi? (oyun görüntüsü gelmemişse beyaz/siyah kalır)
    try:
        out = subprocess.run([arac("ffmpeg"), "-v", "error", "-ss", f"{v / 2:.1f}", "-i", str(yol), "-frames:v", "1",
                              "-vf", "crop=iw:ih/3:0:ih/3,scale=64:36,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, timeout=30, creationflags=_PENCERESIZ).stdout
        if out and max(out) - min(out) < 12:
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


def ses_cikar(kaynak: Path, baslangic: float, sure: float, cikti: Path) -> Path:
    subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(kaynak),
                    "-vn", "-ac", "1", "-ar", "16000", str(cikti)], check=True, creationflags=_PENCERESIZ)
    return cikti


def on_izleme(video: Path, an: float, uzun: float = 1.3) -> float:
    """İLK SANİYE KANCASI: olayın en çarpıcı ~1.3 sn'si videonun en başında bir kez gösterilir, ardından
    video baştan (olayın öncesinden) başlar. İzleyici ilk saniyede "ne olacak?" der ve kaydırmaz —
    kısa videoda izlenme süresini en çok artıran numara. Geçişte kısa beyaz flaş. Dönüş: eklenen saniye."""
    video = Path(video)
    bas = max(0.0, an - 0.25)
    gecici = video.with_name(video.stem + "_kanca.mp4")
    try:
        subprocess.run(
            [arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video.resolve()),
             "-filter_complex",
             f"[0:v]trim={bas:.2f}:{bas + uzun:.2f},setpts=PTS-STARTPTS[tv];"
             f"[0:a]atrim={bas:.2f}:{bas + uzun:.2f},asetpts=PTS-STARTPTS,afade=t=out:st={uzun - 0.12:.2f}:d=0.12[ta];"
             f"[0:v]setpts=PTS-STARTPTS,fade=t=in:st=0:d=0.18:color=white[av];"
             f"[0:a]asetpts=PTS-STARTPTS[aa];"
             f"[tv][ta][av][aa]concat=n=2:v=1:a=1[v][a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
             "-maxrate", "6M", "-bufsize", "12M", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
             "-movflags", "+faststart", str(gecici.resolve())],
            check=True, creationflags=_PENCERESIZ, timeout=600)
        if gecici.stat().st_size < 10000:
            raise RuntimeError("çıktı boş")
        gecici.replace(video)
        return uzun
    except Exception as e:  # noqa: BLE001
        log.warning("ilk saniye kancası eklenemedi: %r", e)
        gecici.unlink(missing_ok=True)
        return 0.0


def facebook_kopya(kaynak: Path) -> Path:
    """Facebook'un Reels kurallarına birebir uyan kopya. Uymazsa Facebook videoyu Reels değil normal GÖNDERİ
    yapıyor. Kurallar: 9:16 1080x1920, sabit 30 fps, 2 sn'de bir kapalı anahtar kare (GOP), H.264 + yuv420p,
    AAC 48 kHz stereo 128k+, 3-60 sn arası, faststart."""
    cikti = Path(kaynak).with_name(Path(kaynak).stem + "_fb.mp4")
    if cikti.exists() and cikti.stat().st_size > 0:
        return cikti
    try:
        subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(kaynak),
                        "-t", "59.5",
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                               "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
                        "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "veryfast",
                        "-crf", "19", "-maxrate", "10M", "-bufsize", "16M",
                        "-g", "60", "-keyint_min", "60", "-sc_threshold", "0", "-bf", "2",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                        "-movflags", "+faststart", str(cikti)], check=True, creationflags=_PENCERESIZ, timeout=600)
        return cikti
    except Exception as e:  # noqa: BLE001
        log.warning("Facebook kopyası yapılamadı, asıl video gönderiliyor: %r", e)
        cikti.unlink(missing_ok=True)
        return Path(kaynak)


def guvenli_kopya(kaynak: Path) -> Path:
    """Instagram/Threads'in video kurallarına birebir uyan kopya: H.264 High 4.1, 30 fps, 1080x1920,
    AAC 128 kbps 48 kHz stereo, en fazla 90 sn, faststart. (İlk yükleme reddedilirse kullanılır.)"""
    cikti = Path(kaynak).with_name(Path(kaynak).stem + "_uyumlu.mp4")
    if cikti.exists() and cikti.stat().st_size > 0:
        return cikti
    subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(kaynak), "-t", "89",
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                           "fps=30,format=yuv420p",
                    "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "veryfast", "-b:v", "6M",
                    "-maxrate", "8M", "-bufsize", "12M", "-g", "60",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart", str(cikti)], check=True, creationflags=_PENCERESIZ, timeout=600)
    return cikti
