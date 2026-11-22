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
KANCA = {
    "tr": {
        "komik": ["{ad} bunu hiç beklemiyordu", "GTA 6'da işler {ad} için ters gitti", "{ad} ve GTA 6: kısa bir hikâye",
                  "Bu anın zamanlaması kusursuz", "{ad} bu sahneyi unutmayacak"],
        "aksiyon": ["GTA 6'da kontrol {ad_in} elinden çıktı", "{ad_in} yayınındaki en sert an", "Saniyeler içinde her şey değişti",
                    "GTA 6'nın fiziği yine şov yaptı", "{ad} gaza bastı, gerisi tarih"],
        "npc": ["GTA 6 NPC'leri bu sefer karşılık verdi", "Bu NPC'nin tepkisi her şeyi anlatıyor",
                "Rockstar NPC'lerde çıtayı yükseltmiş", "{ad} yanlış kişiye bulaştı"],
        "sok": ["{ad} ekranın başında dondu kaldı", "Bu an {ad_i} bile şaşırttı", "Kimsenin beklemediği bir son",
                "{ad_in} tepkisi her şeyi özetliyor"],
        "chat": ["Chat bu anı konuşmayı bırakmadı", "Yayın bir anda durdu, chat aktı", "{ad_in} chat'i bu anla yıkıldı"],
    },
    "en": {
        "komik": ["{ad} did not see that coming", "GTA 6 had other plans for {ad}", "The timing on this is perfect",
                  "{ad} will be thinking about this one", "A short story about {ad} and GTA 6"],
        "aksiyon": ["Things escalated fast for {ad}", "The wildest moment of {ad}'s stream", "It all changed in seconds",
                    "GTA 6 physics never miss", "{ad} hit the gas and never looked back"],
        "npc": ["The NPCs in GTA 6 fight back now", "This NPC's reaction says it all", "Rockstar went all in on the NPCs",
                "{ad} picked the wrong person"],
        "sok": ["{ad} froze in front of the screen", "Even {ad} couldn't believe this", "Nobody expected this ending",
                "{ad}'s reaction says everything"],
        "chat": ["Chat could not stop talking about this", "The stream stopped and chat went wild",
                 "{ad}'s chat lost it over this"],
    },
}
BAGLAM = {
    "tr": {"komik": "{ad_in} GTA 6 yayınında chat kahkahaya boğuldu.",
           "aksiyon": "{ad_in} GTA 6 yayınından tam bir aksiyon sahnesi.",
           "npc": "GTA 6'nın yapay zekâsı {ad_i} bile şaşırttı.",
           "sok": "{ad_in} GTA 6 yayınında herkesi susturan an.",
           "chat": "{ad_in} GTA 6 yayınında chat'in en hareketli anı."},
    "en": {"komik": "Chat could not stop laughing during {ad}'s GTA 6 stream.",
           "aksiyon": "Pure action from {ad}'s GTA 6 stream.",
           "npc": "GTA 6's AI caught even {ad} off guard.",
           "sok": "The moment that silenced {ad}'s GTA 6 stream.",
           "chat": "The loudest moment in {ad}'s chat during GTA 6."},
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
    kancalar = KANCA[dil][tur]
    if not yuz:   # kamera yoksa "yüz ifadesi / dondu kaldı" gibi şeyler söyleme
        kancalar = [k for k in kancalar if "ekranın başında" not in k and "froze" not in k] or kancalar
    ekler = {"ad": yayinci, "ad_in": tr_ek(yayinci, "in"), "ad_i": tr_ek(yayinci, "i"), "ad_a": tr_ek(yayinci, "a")}
    if dil == "en":
        ekler.update(ad_in=f"{yayinci}'s", ad_i=yayinci, ad_a=yayinci)
    kanca = rnd.choice(kancalar).format(**ekler)
    baglam = BAGLAM[dil][tur].format(**ekler)
    ana = f"“{soz}”" if soz else kanca
    etiketler = [ETIKET[dil][0], ETIKET[dil][1], "#" + re.sub(r"[^\w]", "", yayinci.lower())]
    etiketler += [PLATFORM_ETIKET.get(platform, ETIKET[dil][3]), ETIKET[dil][2]]
    yt = f"{ana} — {yayinci} | GTA 6" if soz else f"{kanca} | GTA 6"
    if len(yt) > 90:
        yt = f"{kanca} | GTA 6"
    return {
        "baslik": soz if soz and len(soz) <= 48 else "",
        "aciklama": ana,
        "baglam": baglam if soz else (baglam if kanca not in baglam else ""),
        "youtube_baslik": yt,
        "hashtagler": list(dict.fromkeys(etiketler)),
    }
