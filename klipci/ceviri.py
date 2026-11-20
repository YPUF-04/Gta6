"""Ücretsiz çeviri (anahtarsız): Google Çeviri'nin herkese açık adresi.

Yabancı dilde (Arapça, Almanca...) konuşan yayıncının altyazısı Türkçe ve İngilizce hesaplar için çevrilir.
Olmazsa None döner; program İngilizce için Whisper'ın kendi çevirisini kullanır.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("ceviri")
ADRES = "https://translate.googleapis.com/translate_a/single"
_AYRAC = "\n"


def cevir(metinler: list[str], hedef: str, kaynak: str = "auto") -> list[str] | None:
    """Her satırı ayrı çevirir (sıra ve sayı korunur). Olmazsa None."""
    if not metinler:
        return []
    temiz = [m.replace("\n", " ").strip() for m in metinler]
    try:
        r = httpx.get(ADRES, params={"client": "gtx", "sl": kaynak or "auto", "tl": hedef, "dt": "t",
                                     "q": _AYRAC.join(temiz)},
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        j = r.json()
        cikti = "".join(parca[0] for parca in (j[0] or []) if parca and parca[0])
        satirlar = [s.strip() for s in cikti.split(_AYRAC)]
        if len(satirlar) != len(temiz):
            # satır sayısı tutmadıysa tek tek çevir
            satirlar = []
            for m in temiz:
                tek = cevir_tek(m, hedef, kaynak)
                if tek is None:
                    return None
                satirlar.append(tek)
        return satirlar
    except Exception as e:  # noqa: BLE001
        log.warning("çeviri yapılamadı (%s→%s): %r", kaynak, hedef, e)
        return None


def cevir_tek(metin: str, hedef: str, kaynak: str = "auto") -> str | None:
    try:
        r = httpx.get(ADRES, params={"client": "gtx", "sl": kaynak or "auto", "tl": hedef, "dt": "t", "q": metin},
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        return "".join(p[0] for p in (r.json()[0] or []) if p and p[0]).strip()
    except Exception as e:  # noqa: BLE001
        log.warning("çeviri yapılamadı: %r", e)
        return None
