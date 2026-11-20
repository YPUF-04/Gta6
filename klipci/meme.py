"""Meme videoları: üstte beyaz kutuda klasik meme yazısı, altta oyundan bir an.

Örn: "Çocukken GTA 6'yı bekleyen ben / Şimdi kasada 'nakit mi kart mı efendim?' diyen ben".
Claude anahtarı varsa güncel trendlere göre yeni memeler yazar; yoksa hazır listeden seçer.
Güvenli konular: bekleme, büyümek, fiyat, PC'ye gelmemesi, NPC'ler, harita... Siyaset, din, etnik köken,
cinsellik, uyuşturucu, kumar/bahis, alkol, gerçek kişilere hakaret YOK (Türkiye'de sorun çıkarmasın).
"""
from __future__ import annotations

import json
import logging
import random
import re
import subprocess
from pathlib import Path

from .kayit import _PENCERESIZ, arac
from .oyun import OYUN

log = logging.getLogger("meme")
W, H = 1080, 1920

HAZIR = {
    "tr": [
        "2013'te: GTA 6 çıkınca her gün oynarım\n2026'da: işten gelip 20 dakika oynayıp uyuyan ben",
        "Çocukken GTA 6'yı bekleyen ben\nŞimdi kasada \"nakit mi kart mı efendim?\" diyen ben",
        "GTA 6 çıktı\nPC oyuncuları: biz hâlâ bekliyoruz",
        "Annem: oyunu bırak yemeğe gel\nBen GTA 6'da 5 yıldızla polisten kaçarken:",
        "GTA 6'nın fiyatını gören cüzdanım:",
        "12 yıl bekledim\nİlk görevde kaybolan ben:",
        "Arkadaş: GTA 6 nasıl?\nBen 6 saattir sadece arabayla gezerken:",
        "GTA 5'i 12 yıl oynayan nesil\nGTA 6'yı ilk açtığında:",
        "\"Haritanın her yerini gezerim\"\n3 saat sonra hâlâ sahilde dolaşan ben:",
        "Okul bitti, askerlik bitti, iş buldum\nGTA 6 sonunda çıktı",
        "NPC'lerin bu kadar gerçekçi olduğunu bilmiyordum\n(bir NPC az önce bana laf soktu)",
        "GTA 6 inerken internetim:",
        "Hikâyeye başlayacaktım\n4 saattir kıyafet seçen ben:",
        "\"Bu sefer kurallara uyacağım\"\nGTA 6'da 30 saniye sonra:",
    ],
    "en": [
        "Me in 2013: I'll play GTA 6 every day\nMe in 2026: 20 minutes after work, then sleep",
        "Me as a kid waiting for GTA 6\nMe now at the register: \"cash or card, sir?\"",
        "GTA 6 is finally out\nPC players: still waiting",
        "Mom: dinner's ready\nMe running from 5 stars in GTA 6:",
        "My wallet seeing the GTA 6 price:",
        "Waited 12 years\njust to get lost in the first mission:",
        "Friend: how's GTA 6?\nMe 6 hours in, still just driving around:",
        "The generation that played GTA 5 for 12 years\nopening GTA 6 for the first time:",
        "\"I'm gonna explore the whole map\"\nMe 3 hours later, still at the beach:",
        "Finished school, got a job, paid taxes\nGTA 6 finally drops",
        "Didn't know NPCs could be this realistic\n(an NPC just roasted me)",
        "My internet downloading GTA 6:",
        "Was gonna start the story\n4 hours later still picking an outfit:",
        "\"This time I'll follow the rules\"\nMe in GTA 6, 30 seconds later:",
    ],
}
YASAK = re.compile(r"siyaset|politi|din\b|relig|allah|god\b|ırk|race\b|seks|sex|porn|uyuşturucu|drug|weed|esrar|"
                   r"kumar|bahis|casino|gambl|\bbet\b|alkol|alcohol|rakı|beer|bira|terör|terror|intihar|suicid",
                   re.I)

MEME_ISTEK = """Write {adet} short meme texts in {dil} for a {oyun} meme page (Instagram Reels/TikTok).
Format: classic top-text meme placed above a short gameplay clip. 1-2 lines, line break with \\n.
Relatable gamer humour: waiting years for {oyun}, growing up, adult life ("cash or card, sir?"), price, PC delay,
NPCs, the map, getting lost, mom calling for dinner, the download... Sound like a real young person, not an AI.
Strictly avoid: politics, religion, ethnicity, sexual content, drugs, gambling/betting, alcohol, insulting
real people or brands. {trend}
Return JSON only: {{"memeler": ["...", "..."], "aciklamalar": ["one short caption per meme with 1-2 emoji"]}}"""


def meme_metinleri(yazar, dil: str, adet: int, kullanilan: set[str]) -> list[tuple[str, str]]:
    """[(meme yazısı, paylaşım açıklaması)]"""
    out: list[tuple[str, str]] = []
    if getattr(yazar, "client", None):
        try:
            ad = {"tr": "Turkish", "en": "English"}.get(dil, dil)
            trend = f"Trend notes (style hint): {yazar.trend[:600]}" if getattr(yazar, "trend", "") else ""
            r = yazar.client.messages.create(
                model=yazar.model, max_tokens=2000, output_config={"effort": "low"},
                messages=[{"role": "user", "content": MEME_ISTEK.format(adet=adet + 2, dil=ad, oyun=OYUN.kisa,
                                                                        trend=trend)}])
            metin = "".join(b.text for b in r.content if b.type == "text")
            j = json.loads(metin[metin.find("{"):metin.rfind("}") + 1])
            for m, a in zip(j.get("memeler", []), j.get("aciklamalar", []) + [""] * 20):
                m = m.replace("\\n", "\n").strip()
                if m and not YASAK.search(m + " " + a) and m not in kullanilan:
                    out.append((m, a.strip()))
        except Exception as e:  # noqa: BLE001
            log.warning("Claude meme yazamadı, hazır listeden seçiliyor: %r", e)
    if len(out) < adet and OYUN.kisa == "GTA 6":
        havuz = [m for m in HAZIR.get(dil, HAZIR["en"]) if m not in kullanilan] or HAZIR.get(dil, HAZIR["en"])
        random.shuffle(havuz)
        out += [(m, "😭😂" if dil == "tr" else "😭💀") for m in havuz]
    return out[:adet]


def _ass(metin: str) -> str:
    return metin.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def meme_video(ham: Path, metin: str, cikti: Path, imza: str = "", sure: float = 12.0) -> Path:
    """Üstte beyaz kutu + siyah yazı, altta oyun görüntüsü (ortası)."""
    satir = metin.count("\n") + 1 + len(metin) // 34
    kutu = min(760, 220 + 90 * satir)
    oh = H - kutu
    ass = cikti.with_suffix(".ass")
    ass.write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        "Style: Meme,Arial,64,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,0,0,5,60,60,0,1",
        "Style: Imza,Arial,34,&H80FFFFFF,&H80FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,90,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,0:00:00.00,0:10:00.00,Meme,,0,0,0,,{{\\pos({W // 2},{kutu // 2})}}{_ass(metin)}",
    ] + ([f"Dialogue: 1,0:00:00.00,0:10:00.00,Imza,,0,0,0,,{_ass(imza)}"] if imza else [])) + "\n", encoding="utf-8")
    filtre = (f"color=c=white:s={W}x{H}:r=30:d={sure:.2f}[zemin];"
              f"[0:v]setpts=PTS-STARTPTS,crop=min(iw\\,ih*{W}/{oh}):ih:(iw-min(iw\\,ih*{W}/{oh}))/2:0,"
              f"scale={W}:{oh}:force_original_aspect_ratio=increase,crop={W}:{oh},setsar=1,fps=30[oyun];"
              f"[zemin][oyun]overlay=0:{kutu}:shortest=1,format=yuv420p,ass={ass.name}[v]")
    try:
        subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-t", f"{sure:.2f}",
                        "-i", str(Path(ham).resolve()), "-filter_complex", filtre, "-map", "[v]", "-map", "0:a:0?",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-t", f"{sure:.2f}", "-movflags", "+faststart",
                        str(Path(cikti).resolve())], check=True, cwd=str(ass.parent), creationflags=_PENCERESIZ)
    finally:
        ass.unlink(missing_ok=True)
    return cikti
