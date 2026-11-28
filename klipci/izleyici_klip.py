"""İzleyicilerin Kick / Twitch'te kestiği klipler: insanların "bu an güzeldi" diye seçtiği, izlenmesi belli anlar.

Program bunları ham malzeme olarak indirir ve KENDİ editimizden geçirir (düzen, altyazı, kanca, efekt, filtreler).
Yayın kaydında kaçırdığımız ya da izlemediğimiz yayıncıların en iyi anları da böylece gelir.

Kick:   https://kick.com/api/v2/categories/<oyun>/clips?sort=view&time=day  (yoksa kanal klipleri)
Twitch: gql.twitch.tv — oyunun son 24 saatte en çok izlenen klipleri + klibin oynatma adresi
"""
from __future__ import annotations

import logging
import re
import subprocess
import urllib.parse
from pathlib import Path

import httpx

from .kayit import _PENCERESIZ, arac

log = logging.getLogger("izleyici_klip")
TWITCH_WEB_CLIENT = "kimne78kx3ncx6brgo4mv6wki5h1ko"
KICK_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
# Twitch'in kendi web oynatıcısının kullandığı kalıcı sorgu (klibin imzalı mp4 adresi)
TW_KLIP_TOKEN = "36b89d2507fce29e5ca551df756d27c1cfe079e2609642b4390aa4c35796eb11"


def _slug(ad: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", ad.lower()).strip("-")


def _sayi(x) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def kick_ayikla(j) -> list[dict]:
    """Kick'in klip listesi (alan adları sürüme göre değişebiliyor: ikisini de oku)."""
    lst = j.get("clips") if isinstance(j, dict) else j
    if isinstance(lst, dict):
        lst = lst.get("data") or lst.get("clips") or []
    out = []
    for c in lst or []:
        kanal = c.get("channel") or {}
        kaynak = c.get("clip_url") or c.get("video_url") or c.get("playbackUrl") or c.get("playback_url") or ""
        slug = kanal.get("slug") or kanal.get("username") or ""
        if not kaynak or not slug:
            continue
        kat = c.get("category") or {}
        out.append({
            "platform": "kick", "id": str(c.get("id") or ""), "baslik": c.get("title") or "",
            "izlenme": _sayi(c.get("views") or c.get("view_count")),
            "sure": float(c.get("duration") or c.get("durationSeconds") or 0),
            "kanal_ad": str(slug).lower(), "kanal_gorunen": kanal.get("username") or slug,
            "dil": "", "kaynak": kaynak, "kategori": kat.get("name") or "",
            "olgun": bool(c.get("is_mature") or c.get("isMature")),
        })
    return out


async def kick_klipleri(c: httpx.AsyncClient, oyun_adi: str, kanallar: list[str], adet: int = 20) -> list[dict]:
    out: list[dict] = []
    try:
        r = await c.get(f"https://kick.com/api/v2/categories/{_slug(oyun_adi)}/clips",
                        params={"sort": "view", "time": "day"}, headers=KICK_UA)
        if r.status_code == 200:
            out = kick_ayikla(r.json())
    except Exception as e:  # noqa: BLE001
        log.debug("kick kategori klipleri alınamadı: %r", e)
    if len(out) < 5:   # yedek: şu an izlediğimiz / bulduğumuz Kick kanallarının klipleri
        for k in kanallar[:12]:
            try:
                r = await c.get(f"https://kick.com/api/v2/channels/{k}/clips",
                                params={"sort": "view", "time": "day"}, headers=KICK_UA)
                if r.status_code == 200:
                    out += [x for x in kick_ayikla(r.json())
                            if not x["kategori"] or "grand theft" in x["kategori"].lower() or "gta" in x["kategori"].lower()]
            except Exception as e:  # noqa: BLE001
                log.debug("kick kanal klipleri alınamadı (%s): %r", k, e)
    out.sort(key=lambda x: -x["izlenme"])
    return out[:adet]


def twitch_ayikla(j: dict) -> list[dict]:
    oyun = ((j or {}).get("data") or {}).get("game") or {}
    out = []
    for e in ((oyun.get("clips") or {}).get("edges") or []):
        n = e.get("node") or {}
        b = n.get("broadcaster") or {}
        if not n.get("slug") or not b.get("login"):
            continue
        out.append({
            "platform": "twitch", "id": n["slug"], "baslik": n.get("title") or "",
            "izlenme": _sayi(n.get("viewCount")), "sure": float(n.get("durationSeconds") or 0),
            "kanal_ad": b["login"].lower(), "kanal_gorunen": b.get("displayName") or b["login"],
            "dil": str(n.get("language") or "").lower()[:2], "kaynak": "", "kategori": "", "olgun": False,
        })
    return out


async def twitch_klipleri(c: httpx.AsyncClient, oyun_adi: str, adet: int = 20) -> list[dict]:
    q = ("query($n:String!,$f:Int!){game(name:$n){clips(first:$f,criteria:{period:LAST_DAY,sort:VIEWS_DESC})"
         "{edges{node{slug title viewCount durationSeconds language broadcaster{login displayName}}}}}}")
    r = await c.post("https://gql.twitch.tv/gql", headers={"Client-Id": TWITCH_WEB_CLIENT},
                     json={"query": q, "variables": {"n": oyun_adi, "f": adet}})
    r.raise_for_status()
    return twitch_ayikla(r.json())


def twitch_kaynak(slug: str, http: httpx.Client | None = None) -> str:
    """Twitch klibinin imzalı (oynatılabilir) mp4 adresi."""
    h = http or httpx.Client(timeout=20)
    r = h.post("https://gql.twitch.tv/gql", headers={"Client-Id": TWITCH_WEB_CLIENT}, json={
        "operationName": "VideoAccessToken_Clip", "variables": {"slug": slug},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": TW_KLIP_TOKEN}}})
    r.raise_for_status()
    klip = ((r.json() or {}).get("data") or {}).get("clip") or {}
    tok = klip.get("playbackAccessToken") or {}
    kalite = sorted(klip.get("videoQualities") or [], key=lambda q: -_sayi(str(q.get("quality", "0")).rstrip("p")))
    if not kalite or not tok.get("signature"):
        return ""
    return (f"{kalite[0]['sourceURL']}?sig={tok['signature']}"
            f"&token={urllib.parse.quote(tok.get('value', ''))}")


def indir(klip: dict, hedef: Path) -> Path | None:
    """Klibi mp4 olarak indir (yeniden kodlamadan). Olmazsa None."""
    try:
        kaynak = klip.get("kaynak") or (twitch_kaynak(klip["id"]) if klip["platform"] == "twitch" else "")
        if not kaynak:
            return None
        hedef.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([arac("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                        "-user_agent", KICK_UA["User-Agent"], "-i", kaynak, "-t", "120",
                        "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(hedef)],
                       check=True, timeout=300, creationflags=_PENCERESIZ)
        return hedef if hedef.exists() and hedef.stat().st_size > 100_000 else None
    except Exception as e:  # noqa: BLE001
        log.warning("izleyici klibi indirilemedi (%s %s): %r", klip.get("platform"), klip.get("id"), e)
        hedef.unlink(missing_ok=True)
        return None


def harici_puan(izlenme: int, platform: str) -> float:
    """İzleyici klibinin başlangıç puanı: insanlar seçmiş + izlenmiş. 7.2'den başlar, izlenmeyle 9.5'e kadar çıkar."""
    import math
    taban = 50 if platform == "kick" else 150   # Kick'te izlenmeler daha düşük
    return round(min(9.5, 7.2 + 0.8 * max(0.0, math.log10(max(1, izlenme) / taban))), 1)
