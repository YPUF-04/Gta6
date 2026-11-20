"""Hangi yayınlar açık? Twitch, Kick ve YouTube'daki GTA 6 yayınlarını kendisi bulur."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("kesif")

# Kick, tarayıcı gibi görünen tam User-Agent'ı reddediyor; sade olanı kabul ediyor.
KICK_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
# YouTube sade UA'ya farklı sayfa veriyor; normal tarayıcı gibi davran.
YT_HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",
}
TWITCH_WEB_CLIENT = "kimne78kx3ncx6brgo4mv6wki5h1ko"   # twitch.tv sitesinin kendi herkese açık kimliği
from .oyun import OYUN


@dataclass(frozen=True)
class Kanal:
    platform: str   # "twitch" | "kick" | "youtube"
    ad: str         # twitch/kick: kullanıcı adı, youtube: video id
    isim: str = field(default="", compare=False)   # ekranda/açıklamada görünecek ad
    tutamac: str = field(default="", compare=False)  # YouTube kanal adresi (@kullanici)
    dil: str = field(default="", compare=False)      # yayının dili ("tr", "en"...), biliniyorsa
    izleyici: int = field(default=0, compare=False)  # bulunduğu andaki izleyici sayısı

    @property
    def url(self) -> str:
        if self.platform == "twitch":
            return f"https://www.twitch.tv/{self.ad}"
        if self.platform == "kick":
            return f"https://kick.com/{self.ad}"
        return f"https://www.youtube.com/watch?v={self.ad}"

    @property
    def anahtar(self) -> str:
        return f"{self.platform}:{self.ad.lower() if self.platform != 'youtube' else self.ad}"

    @property
    def gorunen(self) -> str:
        return self.isim or self.ad

    @property
    def kredi(self) -> str:
        if self.platform == "twitch":
            return f"twitch.tv/{self.ad}"
        if self.platform == "kick":
            return f"kick.com/{self.ad}"
        return f"YouTube: {self.gorunen}"


# ====================== genel ======================
_session = None


def _sl():
    global _session
    if _session is None:
        import streamlink
        _session = streamlink.Streamlink()
    return _session


def yayinda_mi(k: Kanal) -> bool:
    """Bloklayan çağrı. Kick için Kick'in kendi API'si, diğerleri için streamlink."""
    if k.platform == "kick":
        b = kick_bilgi(k.ad)
        return bool(b and b.get("canli"))
    try:
        return bool(_sl().streams(k.url))
    except Exception as e:  # noqa: BLE001
        log.debug("yayın kontrolü başarısız %s: %s", k.url, e)
        return False


def _sayi(s) -> int:
    if isinstance(s, (int, float)):
        return int(s)
    s = str(s or "")
    m = re.search(r"([\d.,]+)\s*([KkMm]?)", s)
    if not m:
        return 0
    n = m.group(1).replace(",", "")
    try:
        v = float(n) if m.group(2) else float(n.replace(".", ""))
    except ValueError:
        return 0
    return int(v * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1))


# ====================== TWITCH ======================
class TwitchKesif:
    """Anahtar varsa Twitch'in resmi API'si, yoksa twitch.tv sitesinin kullandığı GQL."""

    def __init__(self, oyun_adi: str, client_id: str = "", client_secret: str = "", dil: str = ""):
        self.oyun_adi, self.cid, self.secret, self.dil = oyun_adi, client_id, client_secret, dil
        self._token, self._token_bitis, self._oyun_id = None, 0.0, None

    async def bul(self, c: httpx.AsyncClient, adet: int) -> list[tuple[Kanal, int]]:
        if self.cid and self.secret:
            try:
                return await self._helix(c, adet)
            except Exception as e:  # noqa: BLE001
                log.warning("Twitch resmi API hatası (%s), anahtarsız yönteme geçiliyor", e)
        return await self._gql(c, adet)

    async def _helix(self, c, adet):
        if not self._token or time.time() > self._token_bitis - 60:
            r = await c.post("https://id.twitch.tv/oauth2/token", params={
                "client_id": self.cid, "client_secret": self.secret, "grant_type": "client_credentials"})
            r.raise_for_status()
            j = r.json()
            self._token, self._token_bitis = j["access_token"], time.time() + j["expires_in"]
        h = {"Client-Id": self.cid, "Authorization": f"Bearer {self._token}"}
        if not self._oyun_id:
            r = await c.get("https://api.twitch.tv/helix/games", params={"name": self.oyun_adi}, headers=h)
            r.raise_for_status()
            data = r.json()["data"]
            if not data:
                raise RuntimeError(f"oyun bulunamadı: {self.oyun_adi}")
            self._oyun_id = data[0]["id"]
        p = {"game_id": self._oyun_id, "first": 100, "type": "live"}
        if self.dil:
            p["language"] = self.dil
        r = await c.get("https://api.twitch.tv/helix/streams", params=p, headers=h)
        r.raise_for_status()
        return [(Kanal("twitch", s["user_login"], s.get("user_name", ""), dil=(s.get("language") or "").lower()[:2],
                       izleyici=int(s["viewer_count"])), int(s["viewer_count"])) for s in r.json()["data"]][:adet]

    async def _gql(self, c, adet):
        degisken = {"n": self.oyun_adi, "f": min(100, max(adet, 30))}
        for alanlar in ("login displayName broadcastSettings{language}", "login displayName"):
            q = ("query($n:String!,$f:Int!){game(name:$n){streams(first:$f,options:{sort:VIEWER_COUNT})"
                 "{edges{node{viewersCount broadcaster{" + alanlar + "}}}}}}")
            r = await c.post("https://gql.twitch.tv/gql", headers={"Client-Id": TWITCH_WEB_CLIENT},
                             json={"query": q, "variables": degisken})
            r.raise_for_status()
            j = r.json()
            if not j.get("errors"):
                return twitch_gql_ayikla(j)[:adet]
        raise RuntimeError(f"Twitch GQL hata: {str(j.get('errors'))[:200]}")


def twitch_gql_ayikla(j: dict) -> list[tuple[Kanal, int]]:
    oyun = ((j or {}).get("data") or {}).get("game") or {}
    out = []
    for e in ((oyun.get("streams") or {}).get("edges") or []):
        n = e.get("node") or {}
        b = n.get("broadcaster") or {}
        if b.get("login"):
            dil = str(((b.get("broadcastSettings") or {}).get("language")) or "").lower()[:2]
            izl = int(n.get("viewersCount") or 0)
            out.append((Kanal("twitch", b["login"], b.get("displayName", ""), dil=dil, izleyici=izl), izl))
    return out


# ====================== KICK ======================
def kick_bilgi(slug: str) -> dict | None:
    """kick.com'un kendi sitesinin kullandığı kanal bilgisi: chatroom id, canlı mı, yayın linki."""
    try:
        r = httpx.get(f"https://kick.com/api/v2/channels/{slug}", headers=KICK_UA, timeout=15,
                      follow_redirects=True)
        r.raise_for_status()
        j = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("Kick kanal bilgisi alınamadı (%s): %s", slug, e)
        return None
    canli = bool(j.get("livestream"))
    return {
        "chatroom_id": int((j.get("chatroom") or {}).get("id") or 0) or None,
        "canli": canli,
        "playback_url": j.get("playback_url") or "",
        "isim": (j.get("user") or {}).get("username") or slug,
    }


def kick_chatroom_id(slug: str) -> int | None:
    b = kick_bilgi(slug)
    return b["chatroom_id"] if b else None


class KickKesif:
    """Anahtar varsa Kick'in resmi API'si, yoksa sitenin kendi listesi."""

    def __init__(self, oyun_adi: str, client_id: str = "", client_secret: str = "", dil: str = ""):
        self.oyun_adi, self.cid, self.secret, self.dil = oyun_adi, client_id, client_secret, dil
        self._token, self._token_bitis, self._kat_id = None, 0.0, None

    async def bul(self, c: httpx.AsyncClient, adet: int) -> list[tuple[Kanal, int]]:
        if self.cid and self.secret:
            try:
                return await self._resmi(c, adet)
            except Exception as e:  # noqa: BLE001
                log.warning("Kick resmi API hatası (%s), anahtarsız yönteme geçiliyor", e)
        return await self._site(c, adet)

    async def _resmi(self, c, adet):
        if not self._token or time.time() > self._token_bitis - 60:
            r = await c.post("https://id.kick.com/oauth/token", data={
                "grant_type": "client_credentials", "client_id": self.cid, "client_secret": self.secret})
            r.raise_for_status()
            j = r.json()
            self._token, self._token_bitis = j["access_token"], time.time() + int(j.get("expires_in", 3600))
        h = {"Authorization": f"Bearer {self._token}"}
        if not self._kat_id:
            r = await c.get("https://api.kick.com/public/v2/categories", params={"name": self.oyun_adi}, headers=h)
            r.raise_for_status()
            kat = [k for k in r.json().get("data", []) if OYUN.regex.search(k.get("name", ""))]
            if not kat:
                raise RuntimeError(f"Kick'te {OYUN.kisa} kategorisi bulunamadı")
            self._kat_id = kat[0]["id"]
        out, cursor = [], None
        for _ in range(3):
            p = {"category_id": self._kat_id, "limit": 1000}
            if self.dil:
                p["language_code"] = self.dil
            if cursor:
                p["cursor"] = cursor
            r = await c.get("https://api.kick.com/public/v2/livestreams", params=p, headers=h)
            r.raise_for_status()
            j = r.json()
            for s in j.get("data", []):
                slug = (s.get("channel") or {}).get("slug") or (s.get("broadcaster_user") or {}).get("username")
                if slug:
                    izl = int(s.get("viewer_count") or 0)
                    out.append((Kanal("kick", slug, (s.get("broadcaster_user") or {}).get("username", ""),
                                      dil=dil_kodu(s.get("language_code") or s.get("language")),
                                      izleyici=izl), izl))
            cursor = (j.get("pagination") or {}).get("next_cursor")
            if not cursor:
                break
        out.sort(key=lambda x: -x[1])   # Kick sıralamıyor; izleyiciye göre biz sıralarız
        return out[:adet]

    async def _site(self, c, adet):
        try:
            out = await self._kategori_sayfasi(c, adet)
            if out:
                return out
        except Exception as e:  # noqa: BLE001
            log.info("Kick kategori listesi okunamadı (%r), yedek yöntem deneniyor", e)
        return await self._ozel_liste(c, adet)

    async def _kategori_sayfasi(self, c, adet):
        """kick.com'un kendi kategori sayfasının kullandığı liste (izleyiciye göre sıralı, dil bilgisiyle)."""
        slug = kick_kategori_slug(self.oyun_adi)
        out: list[tuple[Kanal, int]] = []
        for sayfa in range(1, min(6, adet // 24 + 2) + 1):
            r = await c.get(f"https://kick.com/stream/livestreams/{'tr' if self.dil == 'tr' else 'en'}",
                            params={"page": sayfa, "limit": 24, "subcategory": slug, "sort": "desc"},
                            headers=KICK_UA)
            r.raise_for_status()
            j = r.json()
            out += kick_kategori_ayikla(j)
            if not j.get("next_page_url") or len(out) >= adet:
                break
        return out[:adet]

    async def _ozel_liste(self, c, adet):
        out, cursor = [], None
        for _ in range(10):   # 20'şerli sayfalar, izleyiciye göre sıralı
            p = {"limit": 20}
            if cursor:
                p["cursor"] = cursor
            r = await c.get("https://api.kick.com/private/v1/livestreams", params=p, headers=KICK_UA)
            r.raise_for_status()
            j = r.json()
            out += kick_site_ayikla(j)
            cursor = ((j.get("data") or {}).get("pagination") or {}).get("next_cursor") \
                or (j.get("pagination") or {}).get("next_cursor") or j.get("next_cursor")
            if len(out) >= adet or not cursor:
                break
        return out[:adet]


DIL_KODU = {"turkish": "tr", "english": "en", "spanish": "es", "portuguese": "pt", "arabic": "ar", "german": "de",
            "french": "fr", "russian": "ru", "italian": "it", "thai": "th", "polish": "pl", "japanese": "ja",
            "korean": "ko", "dutch": "nl", "indonesian": "id", "vietnamese": "vi", "hindi": "hi", "chinese": "zh"}


def dil_kodu(d: str) -> str:
    d = str(d or "").strip().lower()
    return DIL_KODU.get(d, d[:2] if len(d) <= 3 else "")


def kick_kategori_slug(oyun_adi: str) -> str:
    """'Grand Theft Auto VI' -> 'grand-theft-auto-vi' (Kick'in kategori adresi)."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"\(.*?\)", "", oyun_adi.lower())).strip("-")


def kick_kategori_ayikla(j: dict) -> list[tuple[Kanal, int]]:
    out = []
    for x in (j or {}).get("data") or []:
        ch = x.get("channel") or {}
        slug = ch.get("slug")
        if not slug or x.get("is_live") is False:
            continue
        izl = int(x.get("viewer_count") or x.get("viewers") or 0)
        isim = (ch.get("user") or {}).get("username") or slug
        out.append((Kanal("kick", slug, isim, dil=dil_kodu(x.get("language")), izleyici=izl), izl))
    return out


def kick_site_ayikla(j) -> list[tuple[Kanal, int]]:
    """Belgelenmemiş Kick listesinden GTA 6 yayınlarını çıkar (biçim değişebilir; esnek okur)."""
    out: list[tuple[Kanal, int]] = []

    def gez(o):
        if isinstance(o, dict):
            metin = json.dumps(o.get("category") or o.get("categories") or o.get("game") or "", ensure_ascii=False)
            slug = (o.get("channel") or {}).get("slug") if isinstance(o.get("channel"), dict) else None
            slug = slug or o.get("slug") or o.get("channel_slug")
            izl = o.get("viewer_count", o.get("viewers"))
            if slug and izl is not None and OYUN.regex.search(metin):
                dil = dil_kodu(o.get("language_code") or o.get("language"))
                out.append((Kanal("kick", str(slug), dil=dil, izleyici=_sayi(izl)), _sayi(izl)))
                return
            for v in o.values():
                gez(v)
        elif isinstance(o, list):
            for v in o:
                gez(v)

    gez(j)
    return out


# ====================== YOUTUBE ======================
def _yt_initial(html: str) -> dict:
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.S) \
        or re.search(r'window\["ytInitialData"\]\s*=\s*(\{.*?\});', html, re.S)
    return json.loads(m.group(1)) if m else {}


def youtube_arama_ayikla(data: dict) -> list[tuple[Kanal, int]]:
    out = []

    def metin(x) -> str:
        if not isinstance(x, dict):
            return ""
        return x.get("simpleText") or "".join(r.get("text", "") for r in x.get("runs", []))

    def gez(o):
        if isinstance(o, dict):
            v = o.get("videoRenderer")
            if isinstance(v, dict) and v.get("videoId"):
                ham = json.dumps([v.get("badges"), v.get("thumbnailOverlays")])
                canli = "LIVE" in ham or "watching" in metin(v.get("viewCountText")).lower()
                baslik = metin(v.get("title"))
                kanal = metin(v.get("ownerText")) or metin(v.get("longBylineText"))
                yol = json.dumps(v.get("ownerText") or {})
                m = re.search(r'"canonicalBaseUrl":\s*"/(@[^"]+)"', yol)
                if canli and OYUN.regex.search(baslik + " " + kanal):
                    izl = _sayi(metin(v.get("viewCountText")))
                    # YouTube başlıkları izleyicinin diline otomatik çevirebiliyor: dili başlıktan tahmin etme,
                    # klip yapılırken konuşmadan anlaşılır
                    out.append((Kanal("youtube", v["videoId"], kanal, m.group(1) if m else "",
                                      izleyici=izl), izl))
                return
            for x in o.values():
                gez(x)
        elif isinstance(o, list):
            for x in o:
                gez(x)

    gez(data)
    return out


def youtube_yedek_ayikla(data: dict) -> list[tuple[Kanal, int]]:
    """Kart biçimi ne olursa olsun: içinde video kimliği + 'watching' + oyun adı geçen her kartı al."""
    out, gorulen = [], set()

    def gez(o):
        if isinstance(o, dict):
            vid = o.get("videoId") or o.get("contentId")
            if isinstance(vid, str) and len(vid) == 11 and vid not in gorulen:
                ham = json.dumps(o, ensure_ascii=False)
                m = re.search(r"([\d.,]+\s*[KkMm]?)\s*(?:watching|izleyici|izliyor)", ham)
                if m and OYUN.regex.search(ham) and len(ham) < 60000:
                    gorulen.add(vid)
                    h = re.search(r'"canonicalBaseUrl":\s*"/(@[^"]+)"', ham)
                    isim = h.group(1).lstrip("@") if h else ""
                    out.append((Kanal("youtube", vid, isim, h.group(1) if h else "", izleyici=_sayi(m.group(1))),
                                _sayi(m.group(1))))
                    return
            for x in o.values():
                gez(x)
        elif isinstance(o, list):
            for x in o:
                gez(x)

    gez(data)
    return out


class YoutubeKesif:
    def __init__(self, arama: str = ""):
        self.arama = arama or OYUN.arama

    async def bul(self, c: httpx.AsyncClient, adet: int) -> list[tuple[Kanal, int]]:
        r = await c.get("https://www.youtube.com/results", headers=YT_HDR, params={
            "search_query": self.arama, "sp": "EgJAAQ==", "hl": "en", "gl": "US"})
        r.raise_for_status()
        veri = _yt_initial(r.text)
        out = youtube_arama_ayikla(veri)
        if not out:   # YouTube sayfa yapısını değiştirdiyse (yeni "lockup" kartları) yedek okuma
            out = youtube_yedek_ayikla(veri)
        if not out:
            log.info("YouTube araması sonuç vermedi (sayfa %d KB, veri %s)", len(r.text) // 1024,
                     "var" if veri else "yok — çerez/onay sayfası olabilir")
        out.sort(key=lambda x: -x[1])
        return out[:adet]


def youtube_kanal_canli(handle: str) -> Kanal | None:
    """'@KaiCenat' gibi bir kanal şu an canlıysa o yayının video id'sini döndür."""
    h = handle if handle.startswith(("@", "channel/", "c/")) else "@" + handle
    try:
        r = httpx.get(f"https://www.youtube.com/{h}/live", headers=YT_HDR, timeout=20, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        log.warning("YouTube kanalı açılamadı (%s): %s", handle, e)
        return None
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', r.text)
    if not m or '"isLiveNow":true' not in r.text.replace(" ", ""):
        return None
    h2 = h if h.startswith("@") else handle
    return Kanal("youtube", m.group(1), handle.lstrip("@"), h2)


# ====================== Telegram'dan gelen link / isim ======================
_LINK = [
    ("twitch", re.compile(r"(?:https?://)?(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]{2,25})", re.I)),
    ("kick", re.compile(r"(?:https?://)?(?:www\.)?kick\.com/([A-Za-z0-9_\-]{2,30})", re.I)),
    ("youtube", re.compile(r"(?:https?://)?(?:www\.|m\.)?youtube\.com/(@[\w.\-]{2,40})", re.I)),
]
PLATFORM_ADI = {"twitch": "twitch", "tw": "twitch", "kick": "kick", "k": "kick",
                "youtube": "youtube", "yt": "youtube", "y": "youtube"}


def kanal_coz(metin: str) -> tuple[str, str] | None:
    """'https://kick.com/adinross' / 'twitch kaicenat' / 'youtube @IShowSpeed' -> (platform, ad)."""
    metin = metin.strip()
    for platform, rx in _LINK:
        m = rx.search(metin)
        if m:
            ad = m.group(1)
            return platform, ad if platform == "youtube" else ad.lower()
    parca = metin.split()
    if len(parca) >= 2 and parca[0].lower() in PLATFORM_ADI:
        platform, ad = PLATFORM_ADI[parca[0].lower()], parca[1].strip()
        if platform == "youtube":
            return platform, ad if ad.startswith("@") else "@" + ad
        if re.fullmatch(r"[A-Za-z0-9_\-]{2,30}", ad):
            return platform, ad.lower()
    return None
