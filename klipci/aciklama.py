"""Yapay zekâsız, profesyonel açıklama yazarı.

Klibin kendisinden yola çıkar: yayıncının o an söylediği en iyi cümle (altyazıdan), anın türü (komik / aksiyon /
oyun karakteri / şok), yayıncı ve platform. Rastgele "her videoya yazılabilecek" cümleler yerine, o ana özel
ve temiz bir düzen üretir:

    "Bro what is he doing"                      ← yayıncının sözü (kanca)
    Kai Cenat'ın GTA 6 yayınında chat koptu.    ← bağlam cümlesi
    🎮 Kai Cenat · Twitch                        ← kaynak
    #gta6 #gtavi #kaicenat #gaming #gtaclips    ← seçilmiş etiketler
"""
from __future__ import annotations

import random
import re

# --- anın türüne göre kanca ve bağlam cümleleri (abartısız, temiz, her biri bir duruma özel) ---
# Program ne olduğunu GÖRMÜYOR; bu yüzden olayı uyduran cümleler YOK ("yanlış NPC'ye bulaştı" gibi).
# Söz yoksa başlık sadece gerçek bilgi: yayıncı + oyun. Bağlam cümlesi sadece ÖLÇTÜĞÜMÜZ şeyi söyler
# (chat güldü mü, yayıncı bağırdı mı, ekran hareketli mi).
KANCA = {
    "tr": ["{ad} · GTA 6", "{ad_in} GTA 6 yayınından", "GTA 6 · {ad}"],
    "en": ["{ad} · GTA 6", "From {ad_in} GTA 6 stream", "GTA 6 · {ad}"],
}
# Bağlam cümlesi: editör dili, abartısız, olay uydurmaz, "chat" demez. Her türde birkaç seçenek (her video farklı).
BAGLAM = {
    "tr": {"komik": ["GTA 6'dan günün en eğlenceli anlarından biri.", "Tekrar izlemeye değer bir an.",
                     "GTA 6'da bugün yaşanan en keyifli sahnelerden biri."],
           "aksiyon": ["GTA 6'da tempo bir anda yükseldi.", "Yayının en hareketli sahnelerinden biri.",
                       "Saf GTA 6 aksiyonu."],
           "npc": ["GTA 6'dan günün en eğlenceli anlarından biri.", "Tekrar izlemeye değer bir an."],
           "sok": ["Yayının akıllarda kalan anlarından biri.", "Sesi açıp izlemeye değer.",
                   "Yayının en dikkat çeken anı."],
           "chat": ["Yayının en çok konuşulan anı.", "Günün öne çıkan GTA 6 anlarından biri."]},
    "en": {"komik": ["One of the funniest GTA 6 moments today.", "A moment worth the rewatch.",
                     "Easily one of today's best GTA 6 clips."],
           "aksiyon": ["Things picked up fast in GTA 6.", "One of the most intense moments of the stream.",
                       "Pure GTA 6 action."],
           "npc": ["One of the funniest GTA 6 moments today.", "A moment worth the rewatch."],
           "sok": ["One of the most memorable moments of the stream.", "Turn the sound on for this one.",
                   "The standout moment of the stream."],
           "chat": ["The moment everyone was talking about.", "One of today's standout GTA 6 moments."]},
}
ETIKET = {
    "tr": ["#gta6", "#gtavi", "#gta6türkiye", "#oyun"],
    "en": ["#gta6", "#gtavi", "#gaming", "#gtaclips"],
}
PLATFORM_ETIKET = {"twitch": "#twitchclips", "kick": "#kickclips", "youtube": "#youtubegaming"}
# alıntı yapılmayacak kelimeler (hakaret / nefret)
KABA = ("nigg", "fagg", "retard", "orospu", "amk", "sik", "piç", "yarrak", "kahpe", "fuck", "bitch", "whore", "cunt")


def tr_ek(ad: str, ek: str) -> str:
    """Türkçe ünlü uyumuyla kesme ekli ad: tr_ek('Kai Cenat','in') = Kai Cenat'ın, tr_ek('Coringa','in') = Coringa'nın."""
    ince_kalin = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}
    son_kelime = (ad.split() or [ad])[-1].lower()
    if not any(c in ince_kalin for c in son_kelime):
        # 'G', 'xQc' gibi harflerle okunan adlar: harf adı (ge, ce, si) gibi ünlüyle biter → G'nin, xQc'nin
        son, unlu_bitis = "e", True
    else:
        son = [c for c in son_kelime if c in ince_kalin][-1]
        unlu_bitis = son_kelime[-1:] in ince_kalin
    if ek == "in":
        return f"{ad}'{'n' if unlu_bitis else ''}{ince_kalin[son]}n"
    if ek == "i":
        return f"{ad}'{'y' if unlu_bitis else ''}{ince_kalin[son]}"
    if ek == "a":
        return f"{ad}'{'y' if unlu_bitis else ''}{'a' if son in 'aıou' else 'e'}"
    return ad


def an_turu(gulme: float, aksiyon: float, ses_tepki: float, oyun_ani: bool, tekrar: bool) -> str:
    if oyun_ani:
        return "npc"
    if aksiyon >= 2.0 and gulme < 0.45:
        return "aksiyon"
    if gulme >= 0.3:
        return "komik"
    if ses_tepki >= 8:
        return "sok"
    if tekrar:
        return "chat"
    return "komik" if gulme >= 0.15 else "sok"


def _temiz(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip().strip("\"'“”‘’ ")
    t = re.sub(r"^[,.;:!?-]+|[,;:-]+$", "", t).strip()
    return (t[:1].upper() + t[1:]) if t else ""


def en_iyi_soz(segler: list[tuple[float, float, str]], an: float) -> str:
    """Yayıncının o an söylediği en iyi kısa cümle (3-10 kelime, patlama anına en yakın)."""
    adaylar = []
    for b, e, t in segler:
        t = _temiz(t)
        kel = t.split()
        if not 3 <= len(kel) <= 10 or any(k in t.lower() for k in KABA):
            continue
        if len(set(w.lower() for w in kel)) < max(2, len(kel) // 2):   # "no no no no" gibi tekrarlar
            continue
        uzaklik = 0.0 if b - 1 <= an <= e + 3 else min(abs(an - e), abs(b - an))
        puan = uzaklik - (1.5 if t.endswith(("?", "!")) else 0) + abs(len(kel) - 6) * 0.15
        adaylar.append((puan, t))
    return min(adaylar)[1] if adaylar else ""


def yaz(dil: str, yayinci: str, platform: str, segler: list[tuple[float, float, str]], an: float, tur: str,
        tohum: str = "", yuz: bool = False) -> dict:
    """{'baslik', 'aciklama', 'baglam', 'youtube_baslik', 'hashtagler'}"""
    dil = dil if dil in KANCA else "en"
    rnd = random.Random(tohum)
    soz = en_iyi_soz(segler, an)
    ekler = {"ad": yayinci, "ad_in": tr_ek(yayinci, "in")}
    if dil == "en":
        ekler["ad_in"] = f"{yayinci}'s"
    kanca = rnd.choice(KANCA[dil]).format(**ekler)
    baglam = rnd.choice(BAGLAM[dil][tur])
    ana = f"“{soz}”" if soz else kanca
    etiketler = [ETIKET[dil][0], ETIKET[dil][1], "#" + re.sub(r"[^\w]", "", yayinci.lower())]
    etiketler += [PLATFORM_ETIKET.get(platform, ETIKET[dil][3]), ETIKET[dil][2]]
    yt = f"{ana} — {yayinci} | GTA 6" if soz else f"{kanca} | GTA 6"
    if len(yt) > 90:
        yt = f"{kanca} | GTA 6"
    return {
        "baslik": soz if soz and len(soz) <= 48 else "",
        "aciklama": ana,
        "baglam": baglam,
        "youtube_baslik": yt,
        "hashtagler": list(dict.fromkeys(etiketler)),
    }
