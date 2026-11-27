"""YouTube trendleri: son günlerde en çok izlenen GTA 6 Shorts'larına bakar ve ondan öğrenir.

Başkasının videosunu İNDİRMEZ / paylaşmaz (telif). Sadece "ne tutuyor" bilgisini alır:
- hangi yayıncıların klipleri patlıyor → program o yayıncıların yayınlarını öncelikle izler ve
  paylaşım saatinde onların kliplerine biraz öncelik verir,
- tutan videolar kaç saniye, başlıkları nasıl, hangi etiketleri kullanıyor → /trend ile görürsün,
  en çok kullanılan etiketler açıklamalara eklenir.

YouTube Data API (bağladığın YouTube hesabının anahtarıyla, ücretsiz kota: günde 1-2 arama ~200 birim / 10.000).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

log = logging.getLogger("trend")
API = "https://www.googleapis.com/youtube/v3"


def _sure_sn(iso: str) -> int:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, d, s = (int(x or 0) for x in m.groups())
    return h * 3600 + d * 60 + s


def _sade(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


class Trend:
    def __init__(self, yol: Path):
        self.yol = yol
        try:
            self.veri = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.veri = {}

    @property
    def videolar(self) -> list[dict]:
        return self.veri.get("videolar") or []

    def eski_mi(self, saat: float = 12) -> bool:
        return time.time() - float(self.veri.get("t", 0)) > saat * 3600

    def guncelle(self, erisim: str, sorgular: tuple[str, ...] = ("GTA 6", "GTA VI stream"),
                 gun: int = 4, http: httpx.Client | None = None) -> int:
        """En çok izlenen kısa GTA 6 videolarını çek. Dönüş: kaç video bulundu."""
        h = http or httpx.Client(timeout=30)
        bas = {"Authorization": f"Bearer {erisim}"}
        sonra = (datetime.now(timezone.utc) - timedelta(days=gun)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids: list[str] = []
        for q in sorgular:
            r = h.get(f"{API}/search", headers=bas, params={
                "part": "id", "q": q, "type": "video", "videoDuration": "short", "order": "viewCount",
                "publishedAfter": sonra, "maxResults": 50})
            r.raise_for_status()
            ids += [x["id"]["videoId"] for x in r.json().get("items", []) if x.get("id", {}).get("videoId")]
        ids = list(dict.fromkeys(ids))
        videolar = []
        for i in range(0, len(ids), 50):
            r = h.get(f"{API}/videos", headers=bas, params={
                "part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50])})
            r.raise_for_status()
            for v in r.json().get("items", []):
                sn, st = v.get("snippet") or {}, v.get("statistics") or {}
                metin = f"{sn.get('title', '')} {sn.get('description', '')}"
                if "gta" not in metin.lower():
                    continue
                videolar.append({
                    "id": v["id"], "baslik": sn.get("title", ""), "kanal": sn.get("channelTitle", ""),
                    "aciklama": (sn.get("description") or "")[:500], "etiket": sn.get("tags") or [],
                    "izlenme": int(st.get("viewCount", 0)), "sure": _sure_sn((v.get("contentDetails") or {}).get("duration", "")),
                })
        videolar.sort(key=lambda v: -v["izlenme"])
        self.veri = {"t": time.time(), "videolar": videolar[:100]}
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        self.yol.write_text(json.dumps(self.veri, ensure_ascii=False, indent=1), encoding="utf-8")
        return len(videolar)

    def yayinci_puani(self, *adlar: str) -> float:
        """Bu yayıncının adı popüler GTA 6 Shorts'larında ne kadar geçiyor? (0 = hiç, 3'e kadar)
        İzlenmeye göre ağırlıklı: 1M izlenen video 1 puan."""
        anahtarlar = {_sade(a) for a in adlar if a and len(_sade(a)) >= 4}
        if not anahtarlar:
            return 0.0
        p = 0.0
        for v in self.videolar:
            metin = _sade(f"{v['baslik']} {v['kanal']} {v['aciklama']} {' '.join(v['etiket'])}")
            if any(a in metin for a in anahtarlar):
                p += min(1.0, v["izlenme"] / 1_000_000)
        return round(min(3.0, p), 2)

    def populer_etiketler(self, adet: int = 4) -> list[str]:
        say: dict[str, float] = {}
        for v in self.videolar[:50]:
            for e in re.findall(r"#\w+", f"{v['baslik']} {v['aciklama']}"):
                e = e.lower()
                if len(e) > 3:
                    say[e] = say.get(e, 0) + 1 + v["izlenme"] / 1_000_000
        return [e for e, _ in sorted(say.items(), key=lambda x: -x[1])][:adet]

    def ozet(self, yayincilar: list[str] | None = None) -> str:
        v = self.videolar
        if not v:
            return "📈 Trend verisi henüz yok (YouTube bağlıysa birkaç dakika içinde gelir)."
        sureler = sorted(x["sure"] for x in v[:30] if x["sure"])
        orta = sureler[len(sureler) // 2] if sureler else 0
        satir = [f"📈 Son günlerin en çok izlenen GTA 6 Shorts'ları ({len(v)} video)",
                 f"⏱ Tutan videoların ortası: {orta} sn", ""]
        for x in v[:8]:
            satir.append(f"• {x['izlenme'] / 1000:,.0f}K — {x['baslik'][:70]} ({x['kanal'][:24]}, {x['sure']} sn)")
        et = self.populer_etiketler(6)
        if et:
            satir += ["", "🏷 En çok kullanılan etiketler: " + " ".join(et)]
        if yayincilar:
            sicak = sorted(((self.yayinci_puani(a), a) for a in yayincilar), reverse=True)
            sicak = [f"{a} ({p:.1f})" for p, a in sicak if p > 0][:6]
            if sicak:
                satir += ["", "🔥 Shorts'larda patlayan yayıncılar (öncelik verilir): " + ", ".join(sicak)]
        return "\n".join(satir)
