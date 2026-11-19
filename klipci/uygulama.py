"""Ana program: yayınları bul -> izle -> chat patlayınca kes -> kurgula -> Telegram'a yolla."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import kesif
from .altyazi import Yaziya, kelime_parcala, segment_parcala, tr_buyuk
from .chat import kick_chat, twitch_chat
from .kayit import PARCA_SN, Kaydedici
from .kurgu import ass_yaz, chat_sec, dikey_video, ses_cikar
from .spike import Spike, SpikeDetector
from .telegram import Bot
from .yazar import Yazar, paylasim_metni

log = logging.getLogger("klipci")


@dataclass
class Is:
    kanal: kesif.Kanal
    spike: Spike
    kaynak: Path
    ofset: float
    sure: float
    chat: list = field(default_factory=list)   # (klibe göre sn, kullanıcı, mesaj)


@dataclass
class Izleyici:
    kanal: kesif.Kanal
    kayit: Kaydedici
    algila: SpikeDetector
    gorevler: list[asyncio.Task] = field(default_factory=list)
    oto: bool = False
    chat_log: deque = field(default_factory=lambda: deque(maxlen=20000))


class Uygulama:
    def __init__(self, cfg: dict, kok: Path):
        self.cfg, self.kok = cfg, kok
        self.klasor = (kok / cfg.get("klasor", "klipler")).resolve()
        self.durum_yolu = kok / "durum.json"
        durum = self._durum_oku()
        tg = cfg.get("telegram") or {}
        self.bot = Bot(tg.get("bot_token", ""), tg.get("chat_id") or durum.get("chat_id", ""), self._chat_id_kaydet)
        self.bot.on_onay, self.bot.on_sil, self.bot.on_komut = self._onay, self._sil, self._komut
        self.yazar = Yazar(cfg.get("anthropic_api_key", ""), cfg.get("claude_model", "claude-opus-5-5"))
        a = cfg.get("altyazi") or {}
        self.yaziya = Yaziya(a.get("whisper_model", "small"), a.get("cihaz", "auto")) if a.get("acik", True) else None
        k = (cfg.get("kanallar") or {}).get("twitch_otomatik_kesif") or {}
        self.twitch_kesif = (kesif.TwitchKesif(k["client_id"], k["client_secret"], k.get("oyun_adi", "Grand Theft Auto VI"),
                                               k.get("dil", ""), int(k.get("en_az_izleyici", 0)))
                             if k.get("acik") and k.get("client_id") and k.get("client_secret") else None)
        self.izleyiciler: dict[str, Izleyici] = {}
        self.kuyruk: asyncio.Queue[Is] = asyncio.Queue()
        self.duraklat = False
        self.sayac = {"klip": 0, "onay": 0}
        self._kapali: dict[str, float] = {}   # yakın zamanda kapalı bulunan kanallar

    # ---------- durum ----------
    def _durum_oku(self) -> dict:
        try:
            return json.loads(self.durum_yolu.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _chat_id_kaydet(self, cid: str) -> None:
        d = self._durum_oku()
        d["chat_id"] = cid
        self.durum_yolu.write_text(json.dumps(d), encoding="utf-8")
        log.info("Telegram bağlandı (chat_id=%s)", cid)

    # ---------- kanal yönetimi ----------
    def _adaylar_elle(self) -> list[kesif.Kanal]:
        kn = self.cfg.get("kanallar") or {}
        return ([kesif.Kanal("twitch", a.strip().lower()) for a in (kn.get("twitch") or []) if a]
                + [kesif.Kanal("kick", a.strip().lower()) for a in (kn.get("kick") or []) if a])

    async def yonetici(self) -> None:
        yasak = {y.lower() for y in ((self.cfg.get("kanallar") or {}).get("yasakli") or [])}
        en_fazla = int(self.cfg.get("ayni_anda_en_fazla_kanal", 4))
        while True:
            try:
                # ölenleri temizle / yeniden başlat
                for anahtar, iz in list(self.izleyiciler.items()):
                    if not iz.kayit.calisiyor_mu():
                        canli = await asyncio.to_thread(kesif.yayinda_mi, iz.kanal)
                        if canli and not self.duraklat:
                            log.info("kayıt yeniden başlatılıyor: %s", anahtar)
                            iz.kayit.durdur()
                            iz.kayit.baslat()
                        else:
                            log.info("yayın bitti: %s", anahtar)
                            await self._birak(anahtar)
                if not self.duraklat:
                    adaylar: list[tuple[kesif.Kanal, bool]] = [(k, False) for k in self._adaylar_elle()]
                    if self.twitch_kesif:
                        try:
                            adaylar += [(k, True) for k, _ in await self.twitch_kesif.bul(en_fazla * 2)]
                        except Exception as e:  # noqa: BLE001
                            log.warning("twitch keşif hatası: %s", e)
                    for k, oto in adaylar:
                        if len(self.izleyiciler) >= en_fazla:
                            break
                        if k.ad in yasak or k.anahtar in self.izleyiciler:
                            continue
                        if time.time() - self._kapali.get(k.anahtar, 0) < 300:
                            continue
                        if oto or await asyncio.to_thread(kesif.yayinda_mi, k):
                            await self._baslat(k, oto)
                        else:
                            self._kapali[k.anahtar] = time.time()
            except Exception:  # noqa: BLE001
                log.exception("yönetici hatası")
            await asyncio.sleep(90)

    async def _baslat(self, k: kesif.Kanal, oto: bool) -> None:
        a = self.cfg.get("algilama") or {}
        kl = self.cfg.get("klip") or {}
        det = SpikeDetector(a.get("pencere_sn", 10), a.get("kat", 3.0), a.get("en_az_mesaj", 25),
                            a.get("bekleme_sn", 120), a.get("isinma_sn", 90))
        if k.platform == "kick":
            room = await asyncio.to_thread(kesif.kick_chatroom_id, k.ad)
            if room is None:
                self._kapali[k.anahtar] = time.time()
                return
        kayit = Kaydedici(k.url, self.klasor / "_tampon" / k.anahtar.replace(":", "_"),
                          kl.get("kalite", "720p60,720p,best"), int(kl.get("tampon_sn", 240)))
        kayit.baslat()
        iz = Izleyici(k, kayit, det, oto=oto)

        def mesaj_geldi(ts: float, kim: str, metin: str) -> None:
            det.ekle(ts, metin)
            iz.chat_log.append((ts, kim, metin))

        chat = twitch_chat(k.ad, mesaj_geldi) if k.platform == "twitch" else kick_chat(room, mesaj_geldi, k.ad)
        iz.gorevler = [asyncio.create_task(chat), asyncio.create_task(self._izle(iz))]
        self.izleyiciler[k.anahtar] = iz
        log.info("▶ izleniyor: %s%s", k.anahtar, " (otomatik bulundu)" if oto else "")

    async def _birak(self, anahtar: str) -> None:
        iz = self.izleyiciler.pop(anahtar, None)
        if not iz:
            return
        for g in iz.gorevler:
            g.cancel()
        await asyncio.to_thread(iz.kayit.durdur)
        self._kapali[anahtar] = time.time()

    async def _izle(self, iz: Izleyici) -> None:
        while True:
            await asyncio.sleep(1)
            if int(time.time()) % 15 == 0:
                iz.kayit.temizle()
                sinir = time.time() - iz.kayit.tampon
                while iz.chat_log and iz.chat_log[0][0] < sinir:
                    iz.chat_log.popleft()
            if self.duraklat:
                continue
            s = iz.algila.kontrol(time.time())
            if s:
                log.info("💥 chat patladı: %s (%.0f puan, normalin %.1f katı) %s",
                         iz.kanal.anahtar, s.puan, s.kat, s.kelimeler)
                asyncio.create_task(self._kes(iz, s))

    async def _kes(self, iz: Izleyici, s: Spike) -> None:
        kl = self.cfg.get("klip") or {}
        once, sonra = float(kl.get("once_sn", 22)), float(kl.get("sonra_sn", 12))
        bas, bit = s.zaman - once, s.tetik + sonra
        await asyncio.sleep(max(0.0, bit - time.time()) + PARCA_SN * 2 + 1)
        kid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + iz.kanal.ad
        hedef = self.klasor / "_is" / f"{kid}.ts"
        try:
            sonuc = await asyncio.to_thread(iz.kayit.kes, bas, bit, hedef)
        except Exception as e:  # noqa: BLE001
            log.warning("kesme başarısız: %s", e)
            return
        if not sonuc:
            log.warning("kesilecek görüntü yok (kayıt yeni başlamış olabilir)")
            return
        chat = [(t - bas, k, m) for t, k, m in list(iz.chat_log) if bas <= t <= bit]
        await self.kuyruk.put(Is(iz.kanal, s, sonuc[0], sonuc[1], bit - bas, chat))

    # ---------- kurgu işçisi ----------
    async def isci(self) -> None:
        while True:
            is_ = await self.kuyruk.get()
            try:
                await self._isle(is_)
            except Exception:  # noqa: BLE001
                log.exception("klip işlenemedi")
            finally:
                is_.kaynak.unlink(missing_ok=True)

    async def _isle(self, is_: Is) -> None:
        kid = is_.kaynak.stem
        cozum = None
        if self.yaziya:
            wav = is_.kaynak.with_suffix(".wav")
            await asyncio.to_thread(ses_cikar, is_.kaynak, is_.ofset, is_.sure, wav)
            cozum = await asyncio.to_thread(self.yaziya.coz, wav)
            wav.unlink(missing_ok=True)
        segler = cozum.segmentler if cozum else []
        kaynak_dil = cozum.dil if cozum else ""
        zoom = float((self.cfg.get("klip") or {}).get("zoom", 1.3))
        ce = self.cfg.get("chat_ekrani") or {}
        chat_pop = (chat_sec(is_.chat, is_.sure, int(ce.get("en_fazla_satir", 3)), float(ce.get("sure_sn", 2.2)))
                    if ce.get("acik", True) else [])
        for h in (self.cfg.get("hesaplar") or [{"ad": "TR", "dil": "tr"}]):
            dil, ad = h.get("dil", "tr"), h.get("ad", "TR")
            veri = await asyncio.to_thread(self.yazar.yaz, dil, is_.kanal.ad, is_.kanal.platform, segler,
                                           kaynak_dil, is_.spike.ornek_mesajlar, is_.spike.kelimeler)
            if veri.get("altyazi") and len(veri["altyazi"]) == len(segler) and kaynak_dil != dil:
                alt = segment_parcala([(b, e, t) for (b, e, _), t in zip(segler, veri["altyazi"])])
            elif cozum and kaynak_dil == dil:
                alt = kelime_parcala(cozum.kelimeler)
            else:
                alt = segment_parcala([(b, e, t) for (b, e, _), t in zip(segler, veri.get("altyazi", []))])
            if dil == "tr":
                alt = [(b, e, tr_buyuk(t)) for b, e, t in alt]
            klasor = self.klasor / "bekleyen" / f"{kid}_{ad}"
            klasor.mkdir(parents=True, exist_ok=True)
            ass = klasor / "yazi.ass"
            site = "twitch.tv" if is_.kanal.platform == "twitch" else "kick.com"
            ass_yaz(ass, is_.sure, veri.get("baslik", ""), f"🎥 {site}/{is_.kanal.ad}", h.get("imza", ""), alt, chat_pop)
            mp4 = klasor / f"{kid}_{ad}.mp4"
            await asyncio.to_thread(dikey_video, is_.kaynak, is_.ofset, is_.sure, mp4, ass, zoom)
            ass.unlink(missing_ok=True)
            metin = paylasim_metni(veri, is_.kanal.ad, is_.kanal.platform, dil)
            (klasor / "aciklama.txt").write_text(metin, encoding="utf-8")
            (klasor / "bilgi.json").write_text(json.dumps({
                "kanal": is_.kanal.anahtar, "hesap": ad, "dil": dil, "puan": veri.get("puan"),
                "chat_kat": round(is_.spike.kat, 1), "kelimeler": is_.spike.kelimeler,
                "transkript": [t for _, _, t in segler]}, ensure_ascii=False, indent=1), encoding="utf-8")
            self.sayac["klip"] += 1
            ust = f"[{ad}] 🔥 {is_.kanal.ad} — chat normalin {is_.spike.kat:.1f} katı · viral puanı {veri.get('puan', '?')}/10\n\n"
            try:
                await self.bot.video_gonder(mp4, ust + metin, f"{kid}_{ad}")
            except Exception as e:  # noqa: BLE001
                log.warning("telegram'a gönderilemedi (%s) — klasörde duruyor: %s", e, mp4)
            log.info("✅ klip hazır: %s", mp4)

    # ---------- telegram geri bildirim ----------
    async def _onay(self, kid: str) -> str:
        kaynak = self.klasor / "bekleyen" / kid
        if not kaynak.exists():
            raise RuntimeError("klip bulunamadı")
        hesap = kid.rsplit("_", 1)[-1]
        hedef = self.klasor / "hazir" / hesap / kid
        hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(kaynak), str(hedef))
        self.sayac["onay"] += 1
        return (hedef / "aciklama.txt").read_text(encoding="utf-8")

    async def _sil(self, kid: str) -> None:
        shutil.rmtree(self.klasor / "bekleyen" / kid, ignore_errors=True)

    async def _komut(self, komut: str) -> str:
        if komut == "/durum":
            kanal = "\n".join(f"• {k}" for k in self.izleyiciler) or "— (şu an açık yayın yok)"
            return (f"{'⏸ DURAKLATILDI' if self.duraklat else '▶ Çalışıyor'}\n"
                    f"İzlenen yayınlar:\n{kanal}\n\nBu oturumda: {self.sayac['klip']} klip, "
                    f"{self.sayac['onay']} onay. Kuyrukta: {self.kuyruk.qsize()}")
        if komut == "/duraklat":
            self.duraklat = True
            for a in list(self.izleyiciler):
                await self._birak(a)
            return "⏸ Duraklatıldı. /devam ile tekrar başlar."
        if komut == "/devam":
            self.duraklat = False
            self._kapali.clear()
            return "▶ Devam ediyor, yayınlar aranıyor..."
        return "Komutlar: /durum /duraklat /devam"

    # ---------- çalıştır ----------
    async def calistir(self) -> None:
        if not self.bot.token:
            raise SystemExit("config.yaml içinde telegram.bot_token boş! README'deki adımlara bak.")
        (self.klasor / "_is").mkdir(parents=True, exist_ok=True)
        gorevler = [asyncio.create_task(self.bot.dinle()), asyncio.create_task(self.yonetici()),
                    asyncio.create_task(self.isci())]
        try:
            await self.bot.mesaj("▶ GTA 6 Klipçi açıldı. Yayınlar aranıyor... (/durum)")
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram'a ulaşılamadı: %s", e)
        try:
            await asyncio.gather(*gorevler)
        finally:
            for a in list(self.izleyiciler):
                await self._birak(a)
