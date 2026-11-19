"""Canlı chat dinleyiciler (giriş yapmadan, sadece okuma).

Twitch: anonim IRC (justinfan) websocket.
Kick:   Pusher websocket (kick.com'un kendi sitesinin kullandığı).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Callable

import websockets

log = logging.getLogger("chat")
MesajFn = Callable[[float, str, str], None]   # (zaman, kullanıcı, mesaj)

TWITCH_WS = "wss://irc-ws.chat.twitch.tv:443"
KICK_ORIGIN = "https://kick.com"
KICK_PUSHER = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false"


def parse_twitch_privmsg(line: str) -> tuple[str, str] | None:
    """':nick!nick@nick.tmi.twitch.tv PRIVMSG #kanal :mesaj' -> (nick, mesaj)."""
    if line.startswith("@"):
        line = line.split(" ", 1)[1] if " " in line else ""
    if " PRIVMSG " not in line or not line.startswith(":"):
        return None
    prefix, rest = line[1:].split(" PRIVMSG ", 1)
    nick = prefix.split("!", 1)[0]
    if " :" not in rest:
        return None
    msg = rest.split(" :", 1)[1]
    return nick, msg


async def twitch_chat(kanal: str, on_msg: MesajFn) -> None:
    kanal = kanal.lower().lstrip("#")
    bekle = 2
    while True:
        try:
            async with websockets.connect(TWITCH_WS, ping_interval=60) as ws:
                await ws.send("PASS SCHMOOPIIE")
                await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
                await ws.send(f"JOIN #{kanal}")
                log.info("twitch chat bağlandı: %s", kanal)
                bekle = 2
                async for raw in ws:
                    for line in str(raw).split("\r\n"):
                        if not line:
                            continue
                        if line.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")
                            continue
                        p = parse_twitch_privmsg(line)
                        if p:
                            on_msg(time.time(), p[0], p[1])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("twitch chat koptu (%s): %s — %ss sonra tekrar", kanal, e, bekle)
            await asyncio.sleep(bekle)
            bekle = min(bekle * 2, 60)


def parse_kick_event(raw: str) -> tuple[str, str] | None:
    try:
        ev = json.loads(raw)
    except ValueError:
        return None
    if not str(ev.get("event", "")).endswith("ChatMessageEvent"):
        return None
    data = ev.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    user = (data.get("sender") or {}).get("username", "?")
    return user, str(data.get("content", ""))


def kick_pub_ayikla(cerceve: dict) -> tuple[str, str] | None:
    """Centrifugo yayınından ({"push":{"pub":{"data":{"event","data"}}}}) chat mesajını çıkar."""
    pub = ((cerceve.get("push") or {}).get("pub") or {}).get("data")
    if isinstance(pub, str):
        return parse_kick_event(pub)
    if isinstance(pub, dict):
        return parse_kick_event(json.dumps(pub))
    return None


async def _kick_token(http, client_id: str) -> str:
    r = await http.post("https://web.kick.com/api/v1/realtime/auth/connection", json={"client_id": client_id})
    r.raise_for_status()
    return r.json()["data"]["token"]


async def kick_chat(chatroom_id: int, on_msg: MesajFn, etiket: str = "") -> None:
    """Kick Ekim 2026'da chat'i Pusher'dan Centrifugo'ya taşıdı. Misafir token ile okunur.

    Adımlar (kick.com'un kendi sitesi gibi): misafir token al -> sunucu adresini sor ->
    Origin: https://kick.com ile bağlan -> chatrooms.<id>.v2 kanalına abone ol."""
    import uuid

    import httpx

    bekle = 2
    hdr = {"User-Agent": "Mozilla/5.0", "Origin": KICK_ORIGIN, "Content-Type": "application/json"}
    while True:
        cid = str(uuid.uuid4())
        try:
            async with httpx.AsyncClient(timeout=20, headers=hdr) as http:
                token = await _kick_token(http, cid)
                url = "wss://realtime.us-east-1.platform.kick.com/connection/websocket"
                try:
                    r = await http.post("https://web.kick.com/api/v1/realtime/connection", json={
                        "client": {"id": cid, "type": "web"},
                        "capabilities": {"accepted_providers": [{"provider": "centrifugo"}]}})
                    for c in r.json()["data"]["connections"]:
                        if c.get("provider") == "centrifugo":
                            url = c["credentials"]["url"]
                except Exception:  # noqa: BLE001
                    pass
                async with websockets.connect(url, origin=KICK_ORIGIN, ping_interval=None,
                                              user_agent_header="Mozilla/5.0") as ws:
                    await ws.send(json.dumps({"id": 1, "connect": {"token": token, "name": "js"}}))
                    await ws.send(json.dumps({"id": 2, "subscribe": {"channel": f"chatrooms.{chatroom_id}.v2"}}))
                    log.info("kick chat bağlandı: %s (%s)", etiket, chatroom_id)
                    yenile = time.time() + 40 * 60
                    sira = 3
                    async for raw in ws:
                        for satir in str(raw).splitlines():
                            satir = satir.strip()
                            if not satir:
                                continue
                            if satir == "{}":
                                await ws.send("{}")   # Centrifugo ping -> pong
                                continue
                            try:
                                cer = json.loads(satir)
                            except ValueError:
                                continue
                            if cer.get("error"):
                                raise RuntimeError(f"kick hata: {cer['error']}")
                            if (cer.get("push") or {}).get("disconnect"):
                                raise RuntimeError(f"kick bağlantıyı kapattı: {cer['push']['disconnect']}")
                            p = kick_pub_ayikla(cer)
                            if p:
                                on_msg(time.time(), p[0], p[1])
                            else:
                                bekle = 2
                        if time.time() > yenile:   # token 45 dk yaşıyor
                            yeni = await _kick_token(http, cid)
                            await ws.send(json.dumps({"id": sira, "refresh": {"token": yeni}}))
                            sira += 1
                            yenile = time.time() + 40 * 60
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("kick chat koptu (%s): %s — %ss sonra tekrar", etiket, e, bekle)
            await asyncio.sleep(bekle)
            bekle = min(bekle * 2, 300)


# ====================== YOUTUBE ======================
YT_HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",
}


def youtube_chat_ayikla(j: dict) -> tuple[list[tuple[float, str, str]], str | None, float]:
    """get_live_chat cevabı -> (mesajlar, sonraki continuation, bekleme sn)."""
    lcc = ((j or {}).get("continuationContents") or {}).get("liveChatContinuation") or {}
    mesajlar = []
    for a in lcc.get("actions") or []:
        item = ((a.get("addChatItemAction") or {}).get("item") or {})
        r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not r:
            continue
        parca = []
        for run in (r.get("message") or {}).get("runs") or []:
            if "text" in run:
                parca.append(run["text"])
            elif "emoji" in run:
                kis = (run["emoji"].get("shortcuts") or [""])[0]
                parca.append(run["emoji"].get("emojiId", "") if not kis else kis)
        ts = int(r.get("timestampUsec") or 0) / 1e6 or time.time()
        mesajlar.append((ts, (r.get("authorName") or {}).get("simpleText", "?"), "".join(parca)))
    sonraki, bekle = None, 1.5
    for c in lcc.get("continuations") or []:
        for v in c.values():
            if isinstance(v, dict) and v.get("continuation"):
                sonraki = v["continuation"]
                bekle = int(v.get("timeoutMs") or 1500) / 1000
    return mesajlar, sonraki, bekle


async def youtube_chat(video_id: str, on_msg: MesajFn) -> None:
    """YouTube canlı chat'i, youtube.com'un kendi sohbet penceresi gibi okunur (giriş yok)."""
    import re

    import httpx

    bekle_hata = 3
    while True:
        try:
            async with httpx.AsyncClient(timeout=20, headers=YT_HDR, follow_redirects=True) as http:
                r = await http.get("https://www.youtube.com/live_chat", params={"v": video_id, "is_popout": "1"})
                html = r.text
                key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html)
                ver = re.search(r'"clientVersion":"([^"]+)"', html)
                cont = re.search(r'"continuation":"([^"]+)"', html)
                if not (key and cont):
                    raise RuntimeError("canlı chat bulunamadı (yayın bitmiş ya da chat kapalı olabilir)")
                cont_s = cont.group(1)
                log.info("youtube chat bağlandı: %s", video_id)
                bekle_hata = 3
                gorulen: set[str] = set()
                while cont_s:
                    r = await http.post(
                        f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={key.group(1)}&prettyPrint=false",
                        json={"context": {"client": {"clientName": "WEB",
                                                     "clientVersion": ver.group(1) if ver else "2.20241101.00.00"}},
                              "continuation": cont_s})
                    r.raise_for_status()
                    msgs, cont_s, bekle = youtube_chat_ayikla(r.json())
                    for ts, kim, metin in msgs:
                        anahtar = f"{ts}{kim}{metin}"
                        if anahtar in gorulen:
                            continue
                        gorulen.add(anahtar)
                        on_msg(ts, kim, metin)
                    if len(gorulen) > 20000:
                        gorulen.clear()
                    await asyncio.sleep(min(max(bekle, 0.5), 5))
                raise RuntimeError("chat devamı gelmedi")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("youtube chat koptu (%s): %s — %ss sonra tekrar", video_id, e, bekle_hata)
            await asyncio.sleep(bekle_hata)
            bekle_hata = min(bekle_hata * 2, 120)
