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

import httpx

from . import kesif
from .altyazi import Yaziya, kelime_parcala, segment_parcala, tr_buyuk
from .chat import kick_chat, twitch_chat, youtube_chat
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
        eski = (cfg.get("kanallar") or {}).get("twitch_otomatik_kesif") or {}   # eski ayar dosyası uyumu
        ob = cfg.get("otomatik_bul") or {}
        self.oto_acik = bool(ob.get("acik", eski.get("acik", True)))
        oyun = ob.get("oyun_adi", eski.get("oyun_adi", "Grand Theft Auto VI"))
        dil = ob.get("dil", eski.get("dil", ""))
        self.en_az_izleyici = int(ob.get("en_az_izleyici", eski.get("en_az_izleyici", 300)))
        self.kesifler: dict[str, object] = {}
        if ob.get("twitch", True):
            self.kesifler["twitch"] = kesif.TwitchKesif(oyun, ob.get("twitch_client_id", eski.get("client_id", "")),
                                                        ob.get("twitch_client_secret", eski.get("client_secret", "")), dil)
        if ob.get("kick", True):
            self.kesifler["kick"] = kesif.KickKesif(oyun, ob.get("kick_client_id", ""),
                                                    ob.get("kick_client_secret", ""), dil)
        if ob.get("youtube", True):
            self.kesifler["youtube"] = kesif.YoutubeKesif(ob.get("youtube_arama", "GTA 6"))
        self.izleyiciler: dict[str, Izleyici] = {}
        self.kuyruk: asyncio.Queue[Is] = asyncio.Queue()
        self.duraklat = False
        self.sayac = {"klip": 0, "onay": 0}
        self._uyandir = asyncio.Event()
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
        self._durum_yaz(d)
        log.info("Telegram bağlandı (chat_id=%s)", cid)

    # ---------- kanal yönetimi ----------
    # ---------- elle eklenenler: config.yaml + Telegram'dan eklenenler (durum.json) ----------
    def _liste(self, platform: str) -> list[str]:
        kn = (self.cfg.get("kanallar") or {}).get(platform) or []
        tg = (self._durum_oku().get("ekli") or {}).get(platform) or []
        cikan = set((self._durum_oku().get("cikarilan") or {}).get(platform) or [])
        out = []
        for a in [str(x).strip() for x in list(kn) + list(tg) if x]:
            a = a if platform == "youtube" else a.lower()
            if a not in out and a not in cikan:
                out.append(a)
        return out

    def _yasaklar(self) -> set[str]:
        kn = (self.cfg.get("kanallar") or {}).get("yasakli") or []
        return {str(y).strip().lower().lstrip("@") for y in list(kn) + (self._durum_oku().get("yasakli") or [])}

    def _durum_yaz(self, d: dict) -> None:
        self.durum_yolu.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    def _adaylar_elle(self) -> list[kesif.Kanal]:
        return ([kesif.Kanal("twitch", a) for a in self._liste("twitch")]
                + [kesif.Kanal("kick", a) for a in self._liste("kick")])

    async def _adaylar_oto(self, adet: int) -> list[tuple[kesif.Kanal, int]]:
        if not self.oto_acik or not self.kesifler:
            return []
        out: list[tuple[kesif.Kanal, int]] = []
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            sonuclar = await asyncio.gather(*(k.bul(c, adet) for k in self.kesifler.values()), return_exceptions=True)
        for ad, r in zip(self.kesifler, sonuclar):
            if isinstance(r, BaseException):
                log.warning("%s otomatik bulma hatası: %s", ad, r)
                continue
            log.info("%s: %d GTA 6 yayını bulundu", ad, len(r))
            out += [x for x in r if x[1] >= self.en_az_izleyici]
        out.sort(key=lambda x: -x[1])   # en çok izlenenler önce
        return out

    async def _youtube_elle(self) -> list[kesif.Kanal]:
        hs = self._liste("youtube")
        sonuc = await asyncio.gather(*(asyncio.to_thread(kesif.youtube_kanal_canli, h) for h in hs))
        return [k for k in sonuc if k]

    async def yonetici(self) -> None:
        en_fazla = int(self.cfg.get("ayni_anda_en_fazla_kanal", 8))
        while True:
            try:
                # ölenleri temizle / yeniden başlat
                for anahtar, iz in list(self.izleyiciler.items()):
                    if not iz.kayit.calisiyor_mu():
                        canli = await asyncio.to_thread(kesif.yayinda_mi, iz.kanal)
                        if canli and not self.duraklat:
                            log.info("kayıt yeniden başlatılıyor: %s", anahtar)
                            iz.kayit.durdur()
                            if iz.kanal.platform == "kick":   # imzalı yayın linki yenilenmeli
                                b = await asyncio.to_thread(kesif.kick_bilgi, iz.kanal.ad)
                                if b and b.get("playback_url"):
                                    iz.kayit.url = "hls://" + b["playback_url"]
                            iz.kayit.baslat()
                        else:
                            log.info("yayın bitti: %s", anahtar)
                            await self._birak(anahtar)
                if not self.duraklat:
                    # (kanal, otomatik mi, canlı olduğu zaten belli mi)
                    adaylar: list[tuple[kesif.Kanal, bool, bool]] = [(k, False, False) for k in self._adaylar_elle()]
                    adaylar += [(k, False, True) for k in await self._youtube_elle()]
                    if len(self.izleyiciler) < en_fazla:
                        adaylar += [(k, True, True) for k, _ in await self._adaylar_oto(en_fazla * 2)]
                    yasak = self._yasaklar()
                    for k, oto, kesin in adaylar:
                        if k.ad.lower() in yasak or k.gorunen.lower() in yasak or k.anahtar in self.izleyiciler:
                            continue
                        if time.time() - self._kapali.get(k.anahtar, 0) < 300:
                            continue
                        dolu = len(self.izleyiciler) >= en_fazla
                        if dolu and oto:
                            break
                        if not (kesin or await asyncio.to_thread(kesif.yayinda_mi, k)):
                            self._kapali[k.anahtar] = time.time()
                            continue
                        if dolu:   # senin eklediğin yayıncı açıldı: otomatik bulunan birini çıkar, yer aç
                            oto_iz = [a for a, iz in self.izleyiciler.items() if iz.oto]
                            if not oto_iz:
                                continue
                            log.info("yer açılıyor: %s çıkarıldı, %s giriyor", oto_iz[-1], k.anahtar)
                            await self._birak(oto_iz[-1])
                            self._kapali.pop(oto_iz[-1], None)
                        await self._baslat(k, oto)
            except Exception:  # noqa: BLE001
                log.exception("yönetici hatası")
            self._uyandir.clear()
            try:   # 90 sn bekle; Telegram'dan /ekle gelirse hemen uyan
                await asyncio.wait_for(self._uyandir.wait(), 90)
            except asyncio.TimeoutError:
                pass

    async def _baslat(self, k: kesif.Kanal, oto: bool) -> None:
        a = self.cfg.get("algilama") or {}
        kl = self.cfg.get("klip") or {}
        det = SpikeDetector(a.get("pencere_sn", 10), a.get("kat", 3.0), a.get("en_az_mesaj", 25),
                            a.get("bekleme_sn", 120), a.get("isinma_sn", 90))
        url = k.url
        if k.platform == "kick":
            bilgi = await asyncio.to_thread(kesif.kick_bilgi, k.ad)
            if not bilgi or not bilgi.get("chatroom_id") or not bilgi.get("canli"):
                self._kapali[k.anahtar] = time.time()
                return
            room = bilgi["chatroom_id"]
            if bilgi.get("playback_url"):
                url = "hls://" + bilgi["playback_url"]   # Kick'in kendi yayın linki (tarayıcı gerekmez)
        kayit = Kaydedici(url, self.klasor / "_tampon" / k.anahtar.replace(":", "_"),
                          kl.get("kalite", "720p,720p60,best"), int(kl.get("tampon_sn", 240)))
        kayit.baslat()
        iz = Izleyici(k, kayit, det, oto=oto)

        def mesaj_geldi(ts: float, kim: str, metin: str) -> None:
            det.ekle(ts, metin)
            iz.chat_log.append((ts, kim, metin))

        if k.platform == "twitch":
            chat = twitch_chat(k.ad, mesaj_geldi)
        elif k.platform == "kick":
            chat = kick_chat(room, mesaj_geldi, k.ad)
        else:
            chat = youtube_chat(k.ad, mesaj_geldi)
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
            veri = await asyncio.to_thread(self.yazar.yaz, dil, is_.kanal.gorunen, is_.kanal.platform, segler,
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
            ass_yaz(ass, is_.sure, veri.get("baslik", ""), f"🎥 {is_.kanal.kredi}", h.get("imza", ""), alt, chat_pop)
            mp4 = klasor / f"{kid}_{ad}.mp4"
            await asyncio.to_thread(dikey_video, is_.kaynak, is_.ofset, is_.sure, mp4, ass, zoom)
            ass.unlink(missing_ok=True)
            metin = paylasim_metni(veri, is_.kanal, dil)
            (klasor / "aciklama.txt").write_text(metin, encoding="utf-8")
            (klasor / "bilgi.json").write_text(json.dumps({
                "kanal": is_.kanal.anahtar, "hesap": ad, "dil": dil, "puan": veri.get("puan"),
                "chat_kat": round(is_.spike.kat, 1), "kelimeler": is_.spike.kelimeler,
                "transkript": [t for _, _, t in segler]}, ensure_ascii=False, indent=1), encoding="utf-8")
            self.sayac["klip"] += 1
            ust = f"[{ad}] 🔥 {is_.kanal.gorunen} ({is_.kanal.platform}) — chat normalin {is_.spike.kat:.1f} katı · viral puanı {veri.get('puan', '?')}/10\n\n"
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

    YARDIM = (
        "📋 Komutlar\n\n"
        "/durum — neler izleniyor, kaç klip çıktı\n"
        "/ekle kick adinross — yayıncı ekle (twitch / kick / youtube)\n"
        "   ya da direkt linki at: https://twitch.tv/kaicenat\n"
        "/cikar twitch xqc — listeden çıkar\n"
        "/yasakla xqc — bu yayıncıyı asla klipleme\n"
        "/yasak_kaldir xqc — yasağı kaldır\n"
        "/liste — eklediklerin ve yasaklılar\n"
        "/duraklat — kliplemeyi durdur\n"
        "/devam — tekrar başlat")

    async def _komut(self, metin: str) -> str:
        parca = metin.strip().split(maxsplit=1)
        komut = parca[0].lower().split("@")[0] if parca[0].startswith("/") else ""
        arg = parca[1] if len(parca) > 1 else ""
        if not komut:   # komutsuz mesaj: içinde yayın linki varsa ekle
            return await self._ekle(metin) if kesif.kanal_coz(metin) and "." in metin else ""
        if komut == "/durum":
            satir = []
            for k, iz in self.izleyiciler.items():
                satir.append(f"• {iz.kanal.gorunen} ({iz.kanal.platform})" + (" 🤖" if iz.oto else " ⭐"))
            kanal = "\n".join(satir) or "— (şu an açık yayın yok)"
            return (f"{'⏸ DURAKLATILDI' if self.duraklat else '▶ Çalışıyor'}\n"
                    f"İzlenen yayınlar ({len(self.izleyiciler)}):\n{kanal}\n"
                    f"⭐ = senin eklediğin, 🤖 = otomatik bulunan\n\nBu oturumda: {self.sayac['klip']} klip, "
                    f"{self.sayac['onay']} onay. Kuyrukta: {self.kuyruk.qsize()}")
        if komut == "/ekle":
            return await self._ekle(arg) if arg else "Örnek: /ekle kick adinross  ya da  /ekle https://twitch.tv/kaicenat"
        if komut in ("/cikar", "/çıkar", "/sil"):
            kc = kesif.kanal_coz(arg)
            if not kc:
                return "Örnek: /cikar twitch xqc"
            platform, ad = kc
            d = self._durum_oku()
            ekli = d.setdefault("ekli", {}).setdefault(platform, [])
            if ad in ekli:
                ekli.remove(ad)
            d.setdefault("cikarilan", {}).setdefault(platform, [])
            if ad not in d["cikarilan"][platform]:
                d["cikarilan"][platform].append(ad)
            self._durum_yaz(d)
            for anahtar, iz in list(self.izleyiciler.items()):
                if iz.kanal.platform == platform and not iz.oto and ad.lower().lstrip("@") in (
                        iz.kanal.ad.lower(), iz.kanal.gorunen.lower()):
                    await self._birak(anahtar)
            return f"🗑 {ad} ({platform}) listeden çıkarıldı. (Otomatik bulunursa yine izlenebilir; hiç istemiyorsan /yasakla {ad.lstrip('@')})"
        if komut == "/yasakla":
            ad = (kesif.kanal_coz(arg) or ("", arg.strip()))[1].lower().lstrip("@")
            if not ad:
                return "Örnek: /yasakla xqc"
            d = self._durum_oku()
            if ad not in d.setdefault("yasakli", []):
                d["yasakli"].append(ad)
            self._durum_yaz(d)
            for anahtar, iz in list(self.izleyiciler.items()):
                if ad in (iz.kanal.ad.lower(), iz.kanal.gorunen.lower()):
                    await self._birak(anahtar)
            return f"⛔ {ad} yasaklandı, bir daha kliplenmeyecek."
        if komut in ("/yasak_kaldir", "/yasakkaldir"):
            ad = arg.strip().lower().lstrip("@")
            d = self._durum_oku()
            if ad in (d.get("yasakli") or []):
                d["yasakli"].remove(ad)
                self._durum_yaz(d)
                return f"✅ {ad} yasağı kaldırıldı."
            return f"{ad} yasaklılarda yok (config.yaml'daki yasaklıları oradan silmen lazım)."
        if komut == "/liste":
            out = []
            for p in ("twitch", "kick", "youtube"):
                lst = self._liste(p)
                out.append(f"{p.capitalize()}: " + (", ".join(lst) if lst else "—"))
            yas = sorted(self._yasaklar())
            out.append("⛔ Yasaklı: " + (", ".join(yas) if yas else "—"))
            out.append(f"\n🤖 Otomatik bulma: {'açık' if self.oto_acik else 'kapalı'} "
                       f"({', '.join(self.kesifler) or '-'}), en az {self.en_az_izleyici} izleyici")
            return "\n".join(out)
        if komut == "/duraklat":
            self.duraklat = True
            for a in list(self.izleyiciler):
                await self._birak(a)
            return "⏸ Duraklatıldı. /devam ile tekrar başlar."
        if komut == "/devam":
            self.duraklat = False
            self._kapali.clear()
            self._uyandir.set()
            return "▶ Devam ediyor, yayınlar aranıyor..."
        return self.YARDIM

    async def _ekle(self, metin: str) -> str:
        kc = kesif.kanal_coz(metin)
        if not kc:
            return "Anlayamadım. Örnek: /ekle kick adinross  ya da linki at: https://twitch.tv/kaicenat"
        platform, ad = kc
        d = self._durum_oku()
        ekli = d.setdefault("ekli", {}).setdefault(platform, [])
        if ad not in ekli:
            ekli.append(ad)
        cik = (d.get("cikarilan") or {}).get(platform) or []
        if ad in cik:
            cik.remove(ad)
        y = d.get("yasakli") or []
        if ad.lower().lstrip("@") in y:
            y.remove(ad.lower().lstrip("@"))
        self._durum_yaz(d)
        self._kapali.pop(f"{platform}:{ad.lower()}", None)
        canli = None
        if platform == "kick":
            b = await asyncio.to_thread(kesif.kick_bilgi, ad)
            canli = bool(b and b.get("canli")) if b else None
        elif platform == "twitch":
            canli = await asyncio.to_thread(kesif.yayinda_mi, kesif.Kanal("twitch", ad))
        else:
            canli = bool(await asyncio.to_thread(kesif.youtube_kanal_canli, ad))
        self._uyandir.set()
        durum = ("🔴 şu an yayında, hemen izlemeye başlıyorum" if canli
                 else "⚫ şu an yayında değil, açtığı an izlemeye başlayacağım" if canli is False
                 else "kanal bilgisine ulaşılamadı, yine de listeye ekledim")
        dolu = len(self.izleyiciler) >= int(self.cfg.get("ayni_anda_en_fazla_kanal", 8))
        ek = "\n⚠️ İzleme sınırı dolu; yer açılınca girer (ayni_anda_en_fazla_kanal'ı artırabilirsin)." if dolu and canli else ""
        return f"✅ {ad} ({platform}) eklendi — {durum}.{ek}"

    # ---------- çalıştır ----------
    async def calistir(self) -> None:
        if not self.bot.token:
            raise SystemExit("config.yaml içinde telegram.bot_token boş! README'deki adımlara bak.")
        (self.klasor / "_is").mkdir(parents=True, exist_ok=True)
        n_isci = max(1, int(self.cfg.get("ayni_anda_kurgu", 2)))
        gorevler = [asyncio.create_task(self.bot.dinle()), asyncio.create_task(self.yonetici())]
        gorevler += [asyncio.create_task(self.isci()) for _ in range(n_isci)]
        try:
            await self.bot.komut_menusu()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.bot.mesaj("▶ GTA 6 Klipçi açıldı. Yayınlar aranıyor... (/durum)")
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram'a ulaşılamadı: %s", e)
        try:
            await asyncio.gather(*gorevler)
        finally:
            for a in list(self.izleyiciler):
                await self._birak(a)
