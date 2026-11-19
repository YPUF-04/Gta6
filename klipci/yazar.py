"""Başlık, açıklama, hashtag ve altyazı çevirisi (Claude API). Anahtar yoksa şablonlar."""
from __future__ import annotations

import json
import logging
import random

log = logging.getLogger("yazar")

DIL_ADI = {"tr": "Turkish", "en": "English", "es": "Spanish", "de": "German", "pt": "Portuguese"}

# Viral GTA klip sayfalarının (Instagram/TikTok/Shorts) ortak kalıpları — modele stil rehberi
STIL = """You write for a viral GTA 6 short-form clip page (Reels / TikTok / Shorts).
What works on the biggest clip pages:
- On-screen hook: 3-7 words, curiosity or reaction, no spoilers of the punchline, max 1 emoji.
  Patterns: "Chat couldn't believe this 💀", "He did NOT expect that", "GTA 6 physics are insane",
  "Wait for it...", "Bro really tried it". Never clickbait that lies about the clip.
- Post caption: 1 short punchy line + streamer credit line + 4-6 hashtags.
  Always include #gta6 #gtavi and the streamer credit.
- Write naturally in the target language as a native young gamer would (slang ok, no cringe).
- Base everything ONLY on the transcript and chat reaction you are given."""

SEMA = {
    "type": "object",
    "properties": {
        "baslik": {"type": "string", "description": "on-screen hook, 3-7 words"},
        "aciklama": {"type": "string", "description": "one punchy caption line, no hashtags"},
        "hashtagler": {"type": "array", "items": {"type": "string"}},
        "altyazi": {"type": "array", "items": {"type": "string"},
                    "description": "translation of each transcript segment, same count and order"},
        "puan": {"type": "integer", "description": "1-10 how likely this clip goes viral"},
    },
    "required": ["baslik", "aciklama", "hashtagler", "altyazi", "puan"],
    "additionalProperties": False,
}

SABLON = {
    "tr": ["Chat buna inanamadı 💀", "Bunu beklemiyordu 😂", "GTA 6'da olanlara bak", "Sonuna kadar izle...",
           "Kardeşim ne yaptın 💀", "Chat koptu 😂"],
    "en": ["Chat couldn't believe this 💀", "He did NOT expect that 😂", "GTA 6 is unreal",
           "Wait for it...", "Bro really tried it 💀", "Chat lost it 😂"],
}
TAGS = {"tr": ["#gta6", "#gtavi", "#gta", "#keşfet", "#oyun"],
        "en": ["#gta6", "#gtavi", "#gta", "#gaming", "#fyp"]}


class Yazar:
    def __init__(self, api_key: str = "", model: str = "claude-opus-5-5"):
        self.model = model
        self.client = None
        if api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
            except Exception as e:  # noqa: BLE001
                log.warning("anthropic yüklenemedi: %s", e)

    def yaz(self, dil: str, yayinci: str, platform: str, segmentler: list[tuple[float, float, str]],
            kaynak_dil: str, chat: list[str], kelimeler: list[str]) -> dict:
        if self.client:
            try:
                return self._claude(dil, yayinci, platform, segmentler, kaynak_dil, chat, kelimeler)
            except Exception as e:  # noqa: BLE001
                log.warning("Claude başarısız, şablon kullanılıyor: %s", e)
        return self._sablon(dil, segmentler, kaynak_dil)

    def _claude(self, dil, yayinci, platform, segmentler, kaynak_dil, chat, kelimeler) -> dict:
        hedef = DIL_ADI.get(dil, dil)
        transkript = "\n".join(f"{i}. [{b:.1f}-{e:.1f}s] {t}" for i, (b, e, t) in enumerate(segmentler)) or "(no speech)"
        istek = (
            f"Target language: {hedef}\n"
            f"Streamer: {yayinci} ({platform})\n"
            f"Transcript language: {kaynak_dil or 'unknown'}\n"
            f"Clip transcript (numbered segments):\n{transkript}\n\n"
            f"Live chat exploded right here. Top reactions: {', '.join(kelimeler) or '-'}\n"
            f"Sample chat messages:\n" + "\n".join(chat[-20:]) + "\n\n"
            f"Write the hook (baslik), caption line (aciklama), 4-6 hashtags, a 1-10 virality score, and "
            f"'altyazi': each transcript segment translated to {hedef} (keep count/order; if already {hedef}, "
            f"copy it cleaned up; keep it short and spoken-style)."
        )
        r = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SEMA}},
            system=STIL,
            messages=[{"role": "user", "content": istek}],
        )
        if r.stop_reason == "refusal":
            raise RuntimeError("model reddetti")
        metin = next(b.text for b in r.content if b.type == "text")
        out = json.loads(metin)
        if len(out.get("altyazi", [])) != len(segmentler):
            out["altyazi"] = []
        return out

    def _sablon(self, dil, segmentler, kaynak_dil) -> dict:
        return {
            "baslik": random.choice(SABLON.get(dil, SABLON["en"])),
            "aciklama": random.choice(SABLON.get(dil, SABLON["en"])),
            "hashtagler": TAGS.get(dil, TAGS["en"]),
            # çeviri yok: konuşma zaten hedef dildeyse göster, değilse altyazı koyma
            "altyazi": [t for _, _, t in segmentler] if kaynak_dil == dil else [],
            "puan": 5,
        }


def paylasim_metni(veri: dict, kanal, dil: str) -> str:
    kredi = {"tr": "🎥 Yayıncı", "en": "🎥 Streamer"}.get(dil, "🎥")
    tags = " ".join(t if t.startswith("#") else "#" + t for t in veri.get("hashtagler", []))
    return f"{veri.get('aciklama', '')}\n\n{kredi}: {kanal.gorunen} ({kanal.kredi})\n\n{tags}".strip()
