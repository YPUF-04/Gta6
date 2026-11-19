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
# kick.com'un web sitesinin kullandığı herkese açık Pusher anahtarı
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


async def kick_chat(chatroom_id: int, on_msg: MesajFn, etiket: str = "") -> None:
    bekle = 2
    while True:
        try:
            async with websockets.connect(KICK_PUSHER, ping_interval=None) as ws:
                await ws.send(json.dumps({
                    "event": "pusher:subscribe",
                    "data": {"auth": "", "channel": f"chatrooms.{chatroom_id}.v2"},
                }))
                log.info("kick chat bağlandı: %s (%s)", etiket, chatroom_id)
                bekle = 2

                async def ping():
                    while True:
                        await asyncio.sleep(60)
                        await ws.send(json.dumps({"event": "pusher:ping", "data": {}}))

                pinger = asyncio.create_task(ping())
                try:
                    async for raw in ws:
                        p = parse_kick_event(str(raw))
                        if p:
                            on_msg(time.time(), p[0], p[1])
                finally:
                    pinger.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("kick chat koptu (%s): %s — %ss sonra tekrar", etiket, e, bekle)
            await asyncio.sleep(bekle)
            bekle = min(bekle * 2, 60)
