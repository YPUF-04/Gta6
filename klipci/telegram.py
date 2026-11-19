"""Telegram botu: klipleri telefonuna yollar, sen ✅ / 🗑 basarsın.

Komutlar: /start  /durum  /duraklat  /devam
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

import httpx

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{metod}"


class Bot:
    def __init__(self, token: str, chat_id: str, chat_id_kaydet: Callable[[str], None]):
        self.token = token
        self.chat_id = str(chat_id or "")
        self._kaydet = chat_id_kaydet
        self._offset = 0
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20))
        self.on_onay: Callable[[str], Awaitable[str]] | None = None
        self.on_sil: Callable[[str], Awaitable[None]] | None = None
        self.on_komut: Callable[[str], Awaitable[str]] | None = None

    async def _api(self, metod: str, **kw) -> dict:
        r = await self.http.post(API.format(token=self.token, metod=metod), **kw)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"telegram {metod}: {j.get('description')}")
        return j["result"]

    async def mesaj(self, metin: str, **ek) -> None:
        if not self.chat_id:
            log.warning("Telegram chat_id yok — botuna /start yaz")
            return
        await self._api("sendMessage", data={"chat_id": self.chat_id, "text": metin[:4000], **ek})

    async def video_gonder(self, yol: Path, aciklama: str, klip_id: str) -> None:
        if not self.chat_id:
            log.warning("Telegram chat_id yok — klip sadece klasöre kaydedildi: %s", yol)
            return
        klavye = {"inline_keyboard": [[
            {"text": "✅ Paylaşacağım", "callback_data": f"ok:{klip_id}"},
            {"text": "🗑 Sil", "callback_data": f"sil:{klip_id}"},
        ]]}
        with open(yol, "rb") as f:
            await self._api("sendVideo", data={
                "chat_id": self.chat_id, "caption": aciklama[:1024], "supports_streaming": "true",
                "width": "1080", "height": "1920", "reply_markup": json.dumps(klavye),
            }, files={"video": (yol.name, f, "video/mp4")})

    async def komut_menusu(self) -> None:
        """Telegram'da / yazınca çıkan komut listesi."""
        komutlar = [("durum", "Neler izleniyor, kaç klip çıktı"), ("ekle", "Yayıncı ekle: /ekle kick adinross"),
                    ("cikar", "Yayıncıyı listeden çıkar"), ("yasakla", "Bu yayıncıyı asla klipleme"),
                    ("liste", "Eklediklerim ve yasaklılar"), ("duraklat", "Kliplemeyi durdur"),
                    ("devam", "Tekrar başlat"), ("yardim", "Tüm komutlar")]
        await self._api("setMyCommands", data={"commands": json.dumps(
            [{"command": k, "description": a} for k, a in komutlar], ensure_ascii=False)})

    async def dinle(self) -> None:
        while True:
            try:
                guncel = await self._api("getUpdates", data={
                    "offset": self._offset, "timeout": 50,
                    "allowed_updates": json.dumps(["message", "callback_query"])})
                for u in guncel:
                    self._offset = u["update_id"] + 1
                    await self._isle(u)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("telegram hata: %s", e)
                await asyncio.sleep(5)

    async def _isle(self, u: dict) -> None:
        if "message" in u:
            m = u["message"]
            cid = str(m["chat"]["id"])
            metin = (m.get("text") or "").strip()
            if metin.startswith("/start"):
                if not self.chat_id:
                    self.chat_id = cid
                    self._kaydet(cid)
                if cid == self.chat_id:
                    await self.mesaj("👋 Hazırım! Chat patlayan GTA 6 anlarını buraya yollayacağım.\n"
                                     "Yardım için /yardim yaz.")
                return
            if cid != self.chat_id:
                return  # yabancılara cevap verme
            if self.on_komut and metin:
                try:
                    cevap = await self.on_komut(metin)
                except Exception as e:  # noqa: BLE001
                    cevap = f"Hata: {e}"
                if cevap:
                    await self.mesaj(cevap)
        elif "callback_query" in u:
            q = u["callback_query"]
            if str(q["message"]["chat"]["id"]) != self.chat_id:
                return
            islem, _, klip_id = q.get("data", "").partition(":")
            cevap = ""
            try:
                if islem == "ok" and self.on_onay:
                    metin = await self.on_onay(klip_id)
                    cevap = "Hazır klasörüne taşındı ✅"
                    await self._api("editMessageReplyMarkup", data={
                        "chat_id": self.chat_id, "message_id": q["message"]["message_id"],
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "✅ Onaylandı", "callback_data": "x:"}]]})})
                    # açıklamayı ayrı mesaj olarak at: basılı tut -> kopyala
                    await self.mesaj(metin)
                elif islem == "sil" and self.on_sil:
                    await self.on_sil(klip_id)
                    cevap = "Silindi 🗑"
                    await self._api("deleteMessage", data={
                        "chat_id": self.chat_id, "message_id": q["message"]["message_id"]})
            except Exception as e:  # noqa: BLE001
                cevap = f"Hata: {e}"[:190]
            await self._api("answerCallbackQuery", data={"callback_query_id": q["id"], "text": cevap})
