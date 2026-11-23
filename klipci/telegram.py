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
        # buton: data -> (kısa cevap, yeni mesaj metni | None, yeni butonlar | None)
        self.on_buton: Callable[[str], Awaitable[tuple]] | None = None
        self.on_foto: Callable[[bytes], Awaitable[str]] | None = None
        self.on_belge: Callable[[bytes, str, str], Awaitable[str]] | None = None   # (içerik, dosya adı, açıklama)
        self._arka_gorevler: set = set()

    async def _api(self, metod: str, **kw) -> dict:
        r = await self.http.post(API.format(token=self.token, metod=metod), **kw)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"telegram {metod}: {j.get('description')}")
        return j["result"]

    async def butonlu(self, metin: str, klavye: list) -> None:
        await self.mesaj(metin, reply_markup=json.dumps({"inline_keyboard": klavye}, ensure_ascii=False))

    async def html(self, metin: str, butonlar: list | None = None) -> None:
        """HTML biçimli mesaj (<code> blokları telefonda dokununca kopyalanır)."""
        ek = {"parse_mode": "HTML"}
        if butonlar:
            ek["reply_markup"] = json.dumps({"inline_keyboard": butonlar}, ensure_ascii=False)
        await self.mesaj(metin, **ek)

    async def mesaj(self, metin: str, **ek) -> None:
        if not self.chat_id:
            log.warning("Telegram chat_id yok — botuna /start yaz")
            return
        await self._api("sendMessage", data={"chat_id": self.chat_id, "text": metin[:4000], **ek})

    async def video_gonder(self, yol: Path, aciklama: str, klip_id: str, butonlar: list | None = None) -> None:
        if not self.chat_id:
            raise RuntimeError("Telegram chat_id yok — botuna /start yaz")
        klavye = {"inline_keyboard": butonlar or [
            [{"text": "📤 Hemen paylaş", "callback_data": f"hp:{klip_id}"[:64]},
             {"text": "✅ Sıraya ekle", "callback_data": f"ok:{klip_id}"[:64]}],
            [{"text": "😍 Bayıldım", "callback_data": f"by:{klip_id}"[:64]},
             {"text": "👍 Beğendim", "callback_data": f"bg:{klip_id}"[:64]},
             {"text": "👎", "callback_data": f"sil:{klip_id}"[:64]}],
        ]}
        with open(yol, "rb") as f:
            await self._api("sendVideo", data={
                "chat_id": self.chat_id, "caption": aciklama[:1024], "supports_streaming": "true",
                "width": "1080", "height": "1920", "reply_markup": json.dumps(klavye),
            }, files={"video": (yol.name, f, "video/mp4")})

    async def foto_gonder(self, yol: Path, aciklama: str = "") -> None:
        if not self.chat_id:
            return
        with open(yol, "rb") as f:
            await self._api("sendPhoto", data={"chat_id": self.chat_id, "caption": aciklama[:1024]},
                            files={"photo": (Path(yol).name, f, "image/jpeg")})

    async def komut_menusu(self) -> None:
        """Telegram'da / yazınca çıkan komut listesi."""
        komutlar = [("info", "📋 Tüm komutların listesi"), ("durum", "Neler izleniyor, kaç klip çıktı"), ("sira", "Hazırlanan klipler, hangi aşamada"), ("kayit", "Her yayının kayıt durumu"), ("yayinlar", "Şu an açık yayınlar — dokun, seç"),
                    ("platform", "Twitch / Kick / YouTube aç-kapat"), ("istatistik", "Neyi sevdiğimi öğrendin?"),
                    ("sinir", "Aynı anda kaç yayın izlensin: /sinir 12"), ("kalite", "Video için en düşük puan: /kalite 7"), ("bildirim", "Bilgi mesajları aç/kapat (varsayılan kapalı)"), ("paylasim", "Otomatik paylaşım bağlı mı?"), ("dene", "Paylaşım denemesi (yayınlamadan)"), ("anlik", "Bu puan üstü klipler hemen paylaşılsın"), ("saatler", "Günlük paylaşım saatleri"), ("sade", "Sadece video + puan göster"), ("detay", "Her şeyi göster"), ("ikinci_bot", "Paylaşım kanalı (2. bot) kur"), ("aralik", "Kaç saatte bir paylaşılsın"), ("merge", "Şimdi MERGE videosu yap"), ("sekme", "Şimdi SEKME (+1 top) videosu yap"), ("sarkac", "Şimdi SARKAÇ videosu yap"), ("bugun", "Bugün paylaşılanlar"), ("bagla", "Instagram / YouTube hesabı bağla"), ("meme", "Şimdi meme videosu yap"), ("gunluk", "Günde kaç paylaşım: /gunluk 10"),
                    ("ad", "Tweet tarzı: sayfa adı"), ("ustyazi", "Tweet tarzı: büyük başlık"), ("guncelle", "Programı güncelle (uzaktan)"), ("plan", "Bugünün paylaşım planı"), ("stok", "Hesaplarda kaç video hazır"),
                    ("isim", "Videonun altındaki kullanıcı adı: /isim @hesap"),
                    ("hesap", "TR / EN hesaplarını aç-kapat"),
                    ("twitch", "Twitch yayıncısı ekle: /twitch kaicenat"), ("kick", "Kick yayıncısı ekle: /kick adinross"),
                    ("youtube", "YouTube kanalı ekle: /youtube @IShowSpeed"),
                    ("cikar", "Yayıncıyı listeden çıkar"), ("yasakla", "Bu yayıncıyı asla klipleme"),
                    ("liste", "Eklediklerim ve yasaklılar"), ("duraklat", "Kliplemeyi durdur"),
                    ("devam", "Tekrar başlat")]
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
                log.warning("telegram bağlantı sorunu (internet?): %r", e)
                await asyncio.sleep(5)

    async def _isle(self, u: dict) -> None:
        if "message" in u:
            m = u["message"]
            cid = str(m["chat"]["id"])
            metin = (m.get("text") or m.get("caption") or "").strip()
            if m.get("photo") and str(m["chat"]["id"]) == self.chat_id and self.on_foto:
                if metin.lower().startswith("/profil"):
                    try:
                        dosya = await self._api("getFile", data={"file_id": m["photo"][-1]["file_id"]})
                        r = await self.http.get(f"https://api.telegram.org/file/bot{self.token}/{dosya['file_path']}")
                        r.raise_for_status()
                        await self.mesaj(await self.on_foto(r.content))
                    except Exception as e:  # noqa: BLE001
                        await self.mesaj(f"Fotoğraf kaydedilemedi: {e}")
                else:
                    await self.mesaj("Profil fotoğrafı yapmak için fotoğrafın açıklamasına /profil yaz.")
                return
            if m.get("document") and cid == self.chat_id and self.on_belge:
                try:
                    dosya = await self._api("getFile", data={"file_id": m["document"]["file_id"]})
                    r = await self.http.get(f"https://api.telegram.org/file/bot{self.token}/{dosya['file_path']}")
                    r.raise_for_status()
                    await self.mesaj(await self.on_belge(r.content, m["document"].get("file_name", ""), metin))
                except Exception as e:  # noqa: BLE001
                    await self.mesaj(f"Dosya işlenemedi: {e}"[:300])
                return
            if metin.startswith("/start"):
                if not self.chat_id:
                    self.chat_id = cid
                    self._kaydet(cid)
                if cid == self.chat_id:
                    await self.mesaj("👋 Hazırım! Chat patlayan anları buraya yollayacağım.\n"
                                     "Tüm komutlar için /info yaz.")
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
                if metin.lower().startswith(("/bagla instagram", "/bağla instagram", "/ikinci_bot ", "/bagla facebook ",
                                             "/bağla facebook ", "/bagla threads ", "/bağla threads ")):
                    try:   # anahtar sohbette durmasın
                        await self._api("deleteMessage", data={"chat_id": self.chat_id, "message_id": m["message_id"]})
                    except Exception:  # noqa: BLE001
                        pass
        elif "callback_query" in u:
            q = u["callback_query"]
            if str(q["message"]["chat"]["id"]) != self.chat_id:
                return
            # butona dokununca HEMEN cevap ver (yoksa Telegram'da hiçbir şey olmuyormuş gibi görünür),
            # asıl işi arka planda yap: bot bu sırada başka mesajları da işleyebilsin
            try:
                await self._api("answerCallbackQuery", data={"callback_query_id": q["id"], "text": "⏳"})
            except Exception:  # noqa: BLE001
                pass
            gorev = asyncio.create_task(self._buton_isle(q))
            self._arka_gorevler.add(gorev)
            gorev.add_done_callback(self._arka_gorevler.discard)

    async def _duzenle(self, mid: int, metin: str | None, klavye: list | None) -> None:
        try:
            if metin is not None:
                await self._api("editMessageText", data={
                    "chat_id": self.chat_id, "message_id": mid, "text": metin[:4000],
                    "reply_markup": json.dumps({"inline_keyboard": klavye or []}, ensure_ascii=False)})
            elif klavye is not None:
                await self._api("editMessageReplyMarkup", data={
                    "chat_id": self.chat_id, "message_id": mid,
                    "reply_markup": json.dumps({"inline_keyboard": klavye}, ensure_ascii=False)})
        except RuntimeError as e:
            if "not modified" not in str(e):   # aynı içerik: sorun değil
                raise

    async def _buton_isle(self, q: dict) -> None:
        veri = q.get("data", "")
        islem, _, klip_id = veri.partition(":")
        mid = q["message"]["message_id"]
        try:
            if islem == "ok" and self.on_onay:
                metin = await self.on_onay(klip_id)
                await self._duzenle(mid, None, [[{"text": "✅ Stokta", "callback_data": "x:"}]])
                if metin:
                    await self.mesaj(metin)
            elif islem == "sil" and self.on_sil:
                await self.on_sil(klip_id)
                await self._api("deleteMessage", data={"chat_id": self.chat_id, "message_id": mid})
            elif islem not in ("x", "") and self.on_buton:
                cevap, yeni_metin, yeni_klavye = await self.on_buton(veri)
                await self._duzenle(mid, yeni_metin, yeni_klavye)
                if cevap and islem in ("ek", "ya"):
                    await self.mesaj(cevap)
        except Exception as e:  # noqa: BLE001
            log.warning("buton işlenemedi (%s): %r", veri, e)
            try:
                await self.mesaj(f"⚠️ Olmadı: {e}"[:300])
            except Exception:  # noqa: BLE001
                pass
