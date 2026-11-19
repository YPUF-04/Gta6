"""Hangi yayınlar açık? Yeni GTA 6 yayınlarını bul."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("kesif")


@dataclass(frozen=True)
class Kanal:
    platform: str   # "twitch" | "kick"
    ad: str

    @property
    def url(self) -> str:
        return f"https://www.twitch.tv/{self.ad}" if self.platform == "twitch" else f"https://kick.com/{self.ad}"

    @property
    def anahtar(self) -> str:
        return f"{self.platform}:{self.ad.lower()}"


_session = None


def _sl():
    global _session
    if _session is None:
        import streamlink
        _session = streamlink.Streamlink()
        try:
            from streamlink.plugins.kick import KickAdapter
            _session.http.mount("https://kick.com/", KickAdapter())
        except Exception:  # noqa: BLE001
            pass
    return _session


def yayinda_mi(k: Kanal) -> bool:
    """Streamlink ile yayının açık olup olmadığına bak (giriş gerekmez). Bloklayan çağrı."""
    try:
        return bool(_sl().streams(k.url))
    except Exception as e:  # noqa: BLE001
        log.debug("yayın kontrolü başarısız %s: %s", k.url, e)
        return False


def kick_chatroom_id(ad: str) -> int | None:
    try:
        r = _sl().http.get(f"https://kick.com/api/v2/channels/{ad}",
                           headers={"Accept": "application/json"}, timeout=15)
        return int(r.json()["chatroom"]["id"])
    except Exception as e:  # noqa: BLE001
        log.warning("kick chatroom id alınamadı (%s): %s", ad, e)
        return None


class TwitchKesif:
    """Twitch resmi API ile bir oyunda en çok izlenen açık yayınları bulur."""

    def __init__(self, client_id: str, client_secret: str, oyun_adi: str, dil: str = "",
                 en_az_izleyici: int = 0):
        self.cid, self.secret = client_id, client_secret
        self.oyun_adi, self.dil, self.en_az = oyun_adi, dil, en_az_izleyici
        self._token, self._token_bitis, self._oyun_id = None, 0.0, None

    async def _hdr(self, c: httpx.AsyncClient) -> dict:
        if not self._token or time.time() > self._token_bitis - 60:
            r = await c.post("https://id.twitch.tv/oauth2/token", params={
                "client_id": self.cid, "client_secret": self.secret,
                "grant_type": "client_credentials"})
            r.raise_for_status()
            j = r.json()
            self._token, self._token_bitis = j["access_token"], time.time() + j["expires_in"]
        return {"Client-Id": self.cid, "Authorization": f"Bearer {self._token}"}

    async def bul(self, adet: int) -> list[tuple[Kanal, int]]:
        async with httpx.AsyncClient(timeout=20) as c:
            h = await self._hdr(c)
            if not self._oyun_id:
                r = await c.get("https://api.twitch.tv/helix/games", params={"name": self.oyun_adi}, headers=h)
                r.raise_for_status()
                data = r.json()["data"]
                if not data:
                    log.warning("Twitch'te oyun bulunamadı: %s", self.oyun_adi)
                    return []
                self._oyun_id = data[0]["id"]
            p = {"game_id": self._oyun_id, "first": min(100, max(adet * 3, 20)), "type": "live"}
            if self.dil:
                p["language"] = self.dil
            r = await c.get("https://api.twitch.tv/helix/streams", params=p, headers=h)
            r.raise_for_status()
            out = [(Kanal("twitch", s["user_login"]), int(s["viewer_count"]))
                   for s in r.json()["data"] if int(s["viewer_count"]) >= self.en_az]
            return out[:adet]
