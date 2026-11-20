"""Hangi oyunun klipleri yapılıyor? (config.yaml -> oyun:)  İleride başka oyuna geçmek için tek yer.

Örnek başka oyun:
  oyun:
    ad: "Minecraft"            # Twitch/Kick'teki kategori adı
    kisa: "Minecraft"          # yazılarda geçen kısa ad
    arama: "Minecraft"         # YouTube canlı arama kelimesi
    etiket: "#minecraft"
    eslesme: "minecraft"       # yayın başlığında/kategoride aranacak (regex)
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Oyun:
    ad: str = "Grand Theft Auto VI"
    kisa: str = "GTA 6"
    arama: str = "GTA 6"
    etiket: str = "#gta6"
    eslesme: str = r"gta\s*-?\s*(6|vi)\b|grand theft auto\s*(6|vi)\b"

    @property
    def regex(self) -> re.Pattern:
        return re.compile(self.eslesme, re.I)


OYUN = Oyun()


def ayarla(cfg: dict) -> Oyun:
    o = cfg.get("oyun") or {}
    OYUN.ad = o.get("ad", OYUN.ad)
    OYUN.kisa = o.get("kisa", OYUN.kisa)
    OYUN.arama = o.get("arama", OYUN.kisa if "kisa" in o else OYUN.arama)
    OYUN.etiket = o.get("etiket", OYUN.etiket)
    if "eslesme" in o:
        OYUN.eslesme = o["eslesme"]
    elif "ad" in o:   # oyun değiştiyse adından basit bir eşleşme üret
        kelimeler = {re.escape(x.lower()) for x in (OYUN.ad, OYUN.kisa) if x}
        OYUN.eslesme = "|".join(sorted(kelimeler))
    return OYUN
