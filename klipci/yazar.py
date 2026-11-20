"""Başlık, açıklama, hashtag ve altyazı çevirisi (Claude API). Anahtar yoksa şablonlar."""
from __future__ import annotations

import json
import logging
import random

from .oyun import OYUN

log = logging.getLogger("yazar")

DIL_ADI = {"tr": "Turkish", "en": "English", "es": "Spanish", "de": "German", "pt": "Portuguese"}

# Gerçek GTA 6 klip sayfalarından (Kasım 2026, Instagram/TikTok) çıkan ders:
#  TUTAN:    "Kai Cenat couldn't believe how hard it is to run from the cops in GTA 6 😂😭 #kaicenat #gta6"  (31K beğeni)
#            "N3on is officially the first streamer to play GTA6… he's 18 hours ahead 🤯 #n3on #gta6"     (1.2M izlenme)
#  TUTMAYAN: "Wait for it… Kai Cenat in GTA 6 🤯", "Kai Cenat goes CRAZY in GTA 6 😂 Follow for daily clips",
#            "Clip from Kai Cenat's GTA 6 stream. All credit to…"                                           (8-265 izlenme)
# Yani: yayıncının adı + TAM OLARAK ne olduğu + 1-2 emoji + 2-3 hashtag. Genel/klişe laf = yapay zekâ kokusu.
STIL_SABLON = """You write the text for a {oyun} streamer-clip page on Instagram Reels / TikTok / YouTube Shorts.
Sound like a real human clip-page admin, not like an AI or a marketer.

What actually performs (real posts, Nov 2026):
- "Kai Cenat couldn't believe how hard it is to run from the cops in GTA 6 😂😭 #kaicenat #gta6"  -> 31K likes
- "RaKai left Kai Cenat speechless after calling him to ask how to play GTA VI 😂😭 #kaicenat #rakai #gta6"
- "Bro walked up to two NPCs in GTA 6 and immediately got called a virgin 💀😂"
What flops (generic, AI-sounding): "Wait for it…", "X goes CRAZY in GTA 6", "You won't believe this",
"Watch till the end", "insane moment", "Follow for daily clips", "All credit to…", "epic", "wild ride".

Rules:
- Say WHAT SPECIFICALLY HAPPENED, using the streamer's name and the concrete event from the transcript/chat.
  Pattern: "<Streamer> <did/said/couldn't believe/got ...> <concrete thing> in {oyun} 😂😭".
- If you can't tell what happened from the transcript and chat, keep it short and plain
  (e.g. "Kai Cenat {oyun}'da 😭") and set baslik to "" — never invent events.
- baslik = the on-screen text: the same idea, shorter (max ~9 words), lowercase-ish casual, no hashtags.
- aciklama = the post caption sentence (no hashtags). 1 sentence. Max 2 emoji, only from 😂😭💀🤯😳.
- youtube_baslik = a YouTube Shorts title for the same moment (max 80 chars, specific, like a human wrote it).
- hashtagler = exactly 2-3: the streamer's name as one tag, {etiket}, optionally one more relevant name tag.
  Never #fyp #viral #trending #keşfet spam.
- Never use: "wait for it", "sonuna kadar izle", "inanılmaz an", "çıldırdı", "epic", "insane", "follow",
  "takip et", "beğenmeyi unutma", "link in bio", em dashes.
- Write like a native young speaker of the target language would type it on their phone (casual, natural slang).
- If screenshots are attached, LOOK at them: they are frames from the clip around the moment chat exploded.
  Just walking, driving normally, menus, loading screens, a calm cutscene or a calm streamer = boring (1-3).
- puan: honest 1-10 for how funny/surprising the moment really is for a {oyun} audience. Be strict:
  most moments are 3-6. Give 7+ only if a stranger scrolling would stop and laugh/gasp.
  Give 1-3 if nothing really happens on screen or in what the streamer says (just driving/menus/talking
  to chat), or if chat only exploded because of a sub/gift/donation/raid/giveaway/poll/ad.
- yayinci_konusmasi = indexes of the transcript segments the STREAMER says into their own mic.
  Leave out lines from game characters, cutscenes, NPCs, radio, TV, phone calls in the game, and
  text-to-speech donation messages. In-game dialogue sounds scripted/acted; the streamer reacts,
  talks to chat, swears, laughs, comments on what happens.
The examples above are from GTA 6; apply the same style to {oyun}."""

def _icerik(metin: str, kareler: list[bytes] | None):
    """Metin + (varsa) klipten birkaç kare: yapay zekâ anın gerçekten ilginç olup olmadığını görsün."""
    if not kareler:
        return metin
    import base64
    parca = [{"type": "text", "text": "Frames from the clip (in order, around the moment chat exploded):"}]
    for k in kareler[:5]:
        parca.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.b64encode(k).decode()}})
    parca.append({"type": "text", "text": metin})
    return parca


SEMA = {
    "type": "object",
    "properties": {
        "baslik": {"type": "string", "description": "on-screen text, max ~9 words, or empty string"},
        "aciklama": {"type": "string", "description": "one specific caption sentence, no hashtags"},
        "youtube_baslik": {"type": "string", "description": "YouTube Shorts title, max 80 chars, specific, no hashtags"},
        "hashtagler": {"type": "array", "items": {"type": "string"}},
        "altyazi": {"type": "array", "items": {"type": "string"},
                    "description": "translation of each transcript segment, same count and order"},
        "puan": {"type": "integer", "description": "1-10 how funny/surprising this moment really is"},
        "yayinci_konusmasi": {"type": "array", "items": {"type": "integer"},
                              "description": "indexes of segments spoken by the streamer (not the game)"},
    },
    "required": ["baslik", "aciklama", "youtube_baslik", "hashtagler", "altyazi", "puan", "yayinci_konusmasi"],
    "additionalProperties": False,
}

# Anahtar yoksa: ne olduğunu bilmeden uydurma; sade, insan gibi kısa yaz, ekrana yazı koyma.
SABLON = {
    "tr": ["{ad} {oyun}'da 😭", "{ad} {oyun} 😂😭", "{ad} ve {oyun} 💀"],
    "en": ["{ad} in {oyun} 😭", "{ad} {oyun} 😂😭", "{ad} playing {oyun} 💀"],
}
YASAK_KALIP = ["wait for it", "sonuna kadar", "follow for", "takip et", "link in bio", "all credit", "goes crazy",
               "inanılmaz an", "çıldırdı", "you won't believe", "watch till", "—"]


def etiket(ad: str) -> str:
    import re
    return "#" + re.sub(r"[^\w]", "", ad.lower())


class Yazar:
    def __init__(self, api_key: str = "", model: str = "claude-opus-5-5"):
        self.model = model
        self.client = None
        self.trend = ""   # günlük trend araştırmasının özeti
        if api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
            except Exception as e:  # noqa: BLE001
                log.warning("anthropic yüklenemedi: %s", e)

    def yaz(self, dil: str, yayinci: str, platform: str, segmentler: list[tuple[float, float, str]],
            kaynak_dil: str, chat: list[str], kelimeler: list[str], kareler: list[bytes] | None = None) -> dict:
        if self.client:
            try:
                return self._claude(dil, yayinci, platform, segmentler, kaynak_dil, chat, kelimeler, kareler)
            except Exception as e:  # noqa: BLE001
                log.warning("Claude başarısız, şablon kullanılıyor: %s", e)
        return self._sablon(dil, segmentler, kaynak_dil, yayinci)

    def _claude(self, dil, yayinci, platform, segmentler, kaynak_dil, chat, kelimeler, kareler=None) -> dict:
        hedef = DIL_ADI.get(dil, dil)
        transkript = "\n".join(f"{i}. [{b:.1f}-{e:.1f}s] {t}" for i, (b, e, t) in enumerate(segmentler)) or "(no speech)"
        istek = (
            f"Target language: {hedef}\n"
            f"Streamer: {yayinci} ({platform})\n"
            f"Transcript language: {kaynak_dil or 'unknown'}\n"
            f"Clip transcript (numbered segments):\n{transkript}\n\n"
            f"Live chat exploded right here. Top reactions: {', '.join(kelimeler) or '-'}\n"
            f"Sample chat messages:\n" + "\n".join(chat[-20:]) + "\n\n"
            f"Following the rules, write baslik, aciklama, 2-3 hashtags, an honest strict 1-10 puan, "
            f"yayinci_konusmasi (which segments are the streamer's own voice, not the game), and "
            f"'altyazi': each transcript segment translated to {hedef} (keep count/order; if already {hedef}, "
            f"copy it cleaned up; keep it short and spoken-style)."
        )
        r = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SEMA}},
            system=STIL_SABLON.format(oyun=OYUN.kisa, etiket=OYUN.etiket) + (f"\n\nFresh research on what is trending right now (use it as a style hint only):\n{self.trend}"
                           if self.trend else ""),
            messages=[{"role": "user", "content": _icerik(istek, kareler)}],
        )
        if r.stop_reason == "refusal":
            raise RuntimeError("model reddetti")
        metin = next(b.text for b in r.content if b.type == "text")
        out = json.loads(metin)
        if len(out.get("altyazi", [])) != len(segmentler):
            out["altyazi"] = []
        # klişe/yapay zekâ kokan kalıp kaçarsa ekrandan kaldır
        for alan in ("baslik", "aciklama"):
            if any(k in out.get(alan, "").lower() for k in YASAK_KALIP):
                out[alan] = "" if alan == "baslik" else random.choice(SABLON.get(dil, SABLON["en"])).format(ad=yayinci, oyun=OYUN.kisa)
        tags = [t if t.startswith("#") else "#" + t for t in out.get("hashtagler", [])
                if t.lower().lstrip("#") not in ("fyp", "viral", "trending", "keşfet", "kesfet", "foryou", "explore")]
        out["hashtagler"] = (tags or [etiket(yayinci), OYUN.etiket])[:3]
        return out

    def _sablon(self, dil, segmentler, kaynak_dil, yayinci="") -> dict:
        ad = yayinci or "bro"
        return {
            "baslik": "",   # ne olduğunu bilmiyoruz: ekrana uydurma yazı koyma
            "aciklama": random.choice(SABLON.get(dil, SABLON["en"])).format(ad=ad, oyun=OYUN.kisa),
            "youtube_baslik": (f"{ad} {OYUN.kisa}'da" if dil == "tr" else f"{ad} plays {OYUN.kisa}") + " 😭",
            "hashtagler": [etiket(ad), OYUN.etiket],
            # çeviri yok: konuşma zaten hedef dildeyse göster, değilse altyazı koyma
            "altyazi": [t for _, _, t in segmentler] if kaynak_dil == dil else [],
            "puan": 5,
        }


def paylasim_metni(veri: dict, kanal, dil: str, kredi: bool = True) -> str:
    tags = " ".join(t if t.startswith("#") else "#" + t for t in veri.get("hashtagler", []))
    satir = f"{veri.get('aciklama', '').strip()} {tags}".strip()
    if kredi:
        satir += f"\n\n📺 {kanal.kredi}"
    return satir


def platform_metinleri(veri: dict, kanal, dil: str) -> dict:
    """Instagram / TikTok / YouTube için ayrı, kopyala-yapıştır hazır metinler."""
    tags = [t if t.startswith("#") else "#" + t for t in veri.get("hashtagler", [])][:3]
    cumle = veri.get("aciklama", "").strip()
    kredi = f"📺 {kanal.kredi}"
    yt_baslik = (veri.get("youtube_baslik") or cumle).strip()
    if len(yt_baslik) > 90:
        yt_baslik = yt_baslik[:87].rstrip() + "..."
    return {
        "instagram": f"{cumle} {' '.join(tags)}\n\n{kredi}".strip(),
        "tiktok": f"{cumle} {' '.join(tags)}".strip(),
        "youtube_baslik": f"{yt_baslik} #shorts",
        "youtube_aciklama": f"{cumle}\n\n{kredi}\n{' '.join(tags)} #shorts".strip(),
    }


TREND_ISTEK = """Search the web for what {oyun} streamer clips are doing well on Instagram Reels, TikTok and
YouTube Shorts in the last few days (today is {bugun}). Look at real clip pages and real captions.
Answer in under 120 words, plain text, as practical notes for a clip-page admin:
- which streamers / moments are getting the most views right now,
- 3 real example captions that performed well (quote them),
- any caption/format patterns that are working or flopping.
No intro, no sign-off."""


def trend_arastir(yazar: "Yazar") -> str:
    """Claude'un web aramasıyla son günlerde tutan GTA 6 klip tarzlarını özetler (günde 1 kez)."""
    if not yazar.client:
        return ""
    from datetime import date
    mesajlar = [{"role": "user", "content": TREND_ISTEK.format(bugun=date.today().isoformat(), oyun=OYUN.kisa)}]
    araclar = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    r = None
    for _ in range(4):   # uzun aramalarda "pause_turn" ile devam
        r = yazar.client.messages.create(model=yazar.model, max_tokens=4000, tools=araclar,
                                         output_config={"effort": "low"}, messages=mesajlar)
        if r.stop_reason != "pause_turn":
            break
        mesajlar = [mesajlar[0], {"role": "assistant", "content": r.content}]
    if r is None or r.stop_reason == "refusal":
        return ""
    metin = "".join(b.text for b in r.content if b.type == "text").strip()
    return metin[:1500]


# ---------- chat'in tepkisine göre ekrana düşen makara yazı ----------
TEPKI_TURLERI = {
    "gul": ({"lol", "lmao", "lmfao", "kekw", "omegalul", "lul", "haha", "ahah", "xd", "xdd", "icant", "dead", "💀",
             "😂", "🤣", "skull", "sjsj", "jsjs", "aşdk", "asdasd", "kekl", "lmaooo"},
            {"tr": ["chat koptu 😭", "chat gülmekten öldü 💀", "chat yerlerde 😭", "bu an efsane 😭"],
             "en": ["chat is dying 😭", "chat lost it 💀", "chat can't breathe 😭", "bro what 😭"]}),
    "sok": ({"wtf", "?", "??", "???", "omg", "holy", "no way", "noway", "nah", "bruh", "monkas", "what"},
            {"tr": ["ne oldu az önce 💀", "chat: NE?? 😳", "kimse bunu beklemiyordu 😳", "dur bi dakika 😳"],
             "en": ["what just happened 💀", "nobody saw that coming 😳", "chat: WHAT?? 😳", "hold up 😳"]}),
    "klip": ({"clip", "clipit", "clipthat"},
             {"tr": ["chat: KLİPLEYİN 📸", "chat klip diye bağırıyor 📸"],
              "en": ["chat: CLIP THAT 📸", "chat screaming clip it 📸"]}),
    "w": ({"w", "gg", "pog", "pogchamp", "poggers", "insane", "goat"},
          {"tr": ["chat: W 🔥", "efsane an 🔥", "chat ayakta 🔥"], "en": ["chat: W 🔥", "massive W 🔥", "chat going crazy 🔥"]}),
    "rip": ({"rip", "f", "ripbozo", "l", "help"},
            {"tr": ["RIP 💀", "chat F basıyor 💀", "bitti bu iş 💀"], "en": ["RIP 💀", "chat pressing F 💀", "it's over 💀"]}),
}


def tepki_yazisi(kelimeler: list[str], ornek_mesajlar: list[str], dil: str, tohum: str = "") -> str:
    """Chat'te en çok hangi tepki var? Ona göre kısa, doğal bir yazı ('chat koptu 😭', 'ne oldu az önce 💀')."""
    from .spike import mesaj_puani
    sayac = {t: 0 for t in TEPKI_TURLERI}
    for kelime in list(kelimeler) + [mesaj_puani(m)[1] or "" for m in ornek_mesajlar]:
        k = (kelime or "").lower()
        for tur, (anahtarlar, _) in TEPKI_TURLERI.items():
            if k in anahtarlar or any(k.startswith(a) for a in ("lmao", "kekw", "haha", "xdd")) and tur == "gul":
                sayac[tur] += 1
                break
    tur = max(sayac, key=lambda t: sayac[t])
    if sayac[tur] == 0:
        return ""
    secenek = TEPKI_TURLERI[tur][1].get(dil, TEPKI_TURLERI[tur][1]["en"])
    return random.Random(tohum).choice(secenek)
