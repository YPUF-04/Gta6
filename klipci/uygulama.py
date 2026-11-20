"""Ana program: yayınları bul -> izle -> chat patlayınca kes -> kurgula -> Telegram'a yolla."""
from __future__ import annotations

import asyncio
import random
import re
import json
import logging
import shutil
import subprocess
from datetime import date as tarih, datetime as zaman, timedelta
from html import escape
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from . import kesif
from .altyazi import Yaziya, kelime_parcala, segment_parcala, tr_buyuk
from .chat import kick_chat, twitch_chat, youtube_chat
from .kayit import _PENCERESIZ, PARCA_SN, Kaydedici, arac, yetim_kayitlari_kapat
from . import plan as planmod
from . import meme, puan, yuz
from . import SURUM
from .oyun import OYUN, ayarla as oyun_ayarla
from .kurgu import ass_yaz, chat_sec, dikey_video, ses_cikar, tweet_video, video_saglam_mi
from .spike import Spike, SpikeDetector, mesaj_puani, yazi_dili
from .oyunsesi import hareketsiz_oran, oyun_altyazi_anlari, oyun_konusmasi_mi, yuz_tepkisi
from .telegram import Bot
from .yazar import Yazar, paylasim_metni, platform_metinleri, tepki_yazisi, trend_arastir

log = logging.getLogger("klipci")
# TEST'te üç platformda da çalışan kalite. 1080p60'ta Kick/YouTube kayıtları bozuluyor ve 25 yayında
# bağlantı yetmiyordu; 720p yüz bulma için de yeterli.
YENI_KALITE = "720p,720p60,best"


@dataclass
class Is:
    kanal: kesif.Kanal
    spike: Spike
    kaynak: Path
    ofset: float
    sure: float
    chat: list = field(default_factory=list)   # (klibe göre sn, kullanıcı, mesaj)
    buyuk: bool = True                          # büyük yayıncı mı (yüzü kullanılsın mı)
    an: float = 0.0                             # klip içinde chat'in patladığı saniye
    takip: str = ""                             # /sira'da görünen iş kimliği


@dataclass
class Izleyici:
    kanal: kesif.Kanal
    kayit: Kaydedici
    algila: SpikeDetector
    gorevler: list[asyncio.Task] = field(default_factory=list)
    oto: bool = False
    son_yenileme: float = 0.0
    chat_log: deque = field(default_factory=lambda: deque(maxlen=20000))
    bos_baslama: int = 0   # üst üste kaç kez kayıt başladı ama hiç görüntü gelmedi


def _ad_anahtar(k: kesif.Kanal) -> str:
    """Platformdan bağımsız yayıncı adı: 'xQc' (kick) == 'xqc' (twitch)."""
    return re.sub(r"[^a-z0-9]", "", (k.gorunen if k.platform == "youtube" else k.ad).lower())


class Uygulama:
    def __init__(self, cfg: dict, kok: Path):
        self.cfg, self.kok = cfg, kok
        oyun_ayarla(cfg)
        self.klasor = (kok / cfg.get("klasor", "klipler")).resolve()
        self.durum_yolu = kok / "durum.json"
        durum = self._durum_oku()
        tg = cfg.get("telegram") or {}
        self.bot = Bot(tg.get("bot_token", ""), tg.get("chat_id") or durum.get("chat_id", ""), self._chat_id_kaydet)
        self.bot.on_onay, self.bot.on_sil, self.bot.on_komut = self._onay, self._sil, self._komut
        self.bot.on_buton = self._buton
        self.bot.on_foto = self._profil_kaydet
        self.yazar = Yazar(cfg.get("anthropic_api_key", ""), cfg.get("claude_model", "claude-opus-5-5"))
        a = cfg.get("altyazi") or {}
        self.yaziya = Yaziya(a.get("whisper_model", "small"), a.get("cihaz", "auto")) if a.get("acik", True) else None
        eski = (cfg.get("kanallar") or {}).get("twitch_otomatik_kesif") or {}   # eski ayar dosyası uyumu
        ob = cfg.get("otomatik_bul") or {}
        self.oto_acik = bool(ob.get("acik", eski.get("acik", True)))
        oyun = ob.get("oyun_adi", eski.get("oyun_adi", OYUN.ad))
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
            self.kesifler["youtube"] = kesif.YoutubeKesif(ob.get("youtube_arama", ""))
        self.izleyiciler: dict[str, Izleyici] = {}
        self.kuyruk: asyncio.Queue[Is] = asyncio.Queue()
        self.duraklat = False
        self.sayac = {"klip": 0, "onay": 0, "patlama": 0, "kotada": 0, "kesilemedi": 0, "hata": 0, "isleniyor": 0,
                      "elenen": 0}
        self._son_puanlar: deque[float] = deque(maxlen=40)
        self._son_gecen = time.time()
        self.son_sorun = ""
        self.basladi = time.time()
        self.son_bulunan: list[tuple[kesif.Kanal, int]] = []
        self.son_tarama = 0.0
        self.ogrenci = puan.Ogrenci(self.klasor / "puan_gecmisi.jsonl")
        self.plan = planmod.Planlayici(self.klasor)
        try:
            self.yazar.trend = (self.klasor / "trend.txt").read_text(encoding="utf-8")
        except OSError:
            pass
        self._uyandir = asyncio.Event()
        self._gonderiliyor: set[str] = set()
        # Az yayınla başla; kayıtlar akıcıysa saglik_ayari yavaş yavaş /sinir'e kadar artırır
        self.etkin_sinir = int(cfg.get("baslangic_yayin_sayisi", 6))
        self.isler: dict[str, dict] = {}   # hazırlanan klipler: /sira
        self.dinamik_kat = float((cfg.get("algilama") or {}).get("kat", 3.0))
        self._spike_gecmisi: list[float] = []
        self._kabul_gecmisi: list[float] = []
        self._yabanci: set[str] = set()   # chat'ine göre başka dilde olduğu anlaşılan yayınlar (bu oturum)
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

    # ---------- hesaplar (TR / EN) ----------
    def _hesaplar(self, hepsi: bool = False) -> list[dict]:
        tanim: dict[str, dict] = {}
        for h in (self.cfg.get("hesaplar") or []) + [{"ad": "TR", "dil": "tr"}, {"ad": "EN", "dil": "en"}]:
            ad = str(h.get("ad", "")).upper()
            if ad and ad not in tanim:
                tanim[ad] = {"ad": ad, "dil": h.get("dil", "tr" if ad == "TR" else "en"), "imza": h.get("imza", "")}
        d = self._durum_oku()
        kapali = set(d.get("hesap_kapali") or [])
        imza = d.get("imza") or {}
        out = []
        for ad, h in tanim.items():
            h["imza"] = imza.get(ad, imza.get("*", h["imza"]))
            if hepsi or ad not in kapali:
                out.append(h)
        return out

    def _hedef_hesaplar(self, kaynak_dil: str) -> list[dict]:
        """Türkçe yayın -> Türkçe hesap, İngilizce yayın -> İngilizce hesap. Başka dil -> İngilizce hesap."""
        hesaplar = self._hesaplar()
        if not self.cfg.get("dil_yonlendirme", True) or len(hesaplar) <= 1:
            return hesaplar
        kaynak_dil = (kaynak_dil or "").lower()[:2]
        uyan = [h for h in hesaplar if h["dil"] == kaynak_dil]
        if uyan:
            return uyan
        en = [h for h in hesaplar if h["dil"] == "en"]
        return en or hesaplar[:1]

    VARSAYILAN_UST = {"tr": "{oyun}'NIN EN İYİ ANLARI", "en": "{oyun} MOMENTS YOU NEED TO SEE"}

    def _sayfa(self, h: dict) -> dict:
        """Tweet tarzı üst kısım: sayfa adı, @kullanıcı, büyük başlık, profil fotoğrafı (Telegram'dan ayarlanır)."""
        d = self._durum_oku().get("sayfa") or {}
        # /ad ya da /isim girilmediyse ekranda isim YOK (uydurma bir sayfa adı yazılmaz)
        ad = (d.get("ad") or {}).get(h["ad"]) or (d.get("ad") or {}).get("*") or \
            (h.get("imza") or "").lstrip("@")
        ust = (d.get("ust") or {}).get(h["ad"]) or (d.get("ust") or {}).get("*") or \
            self.VARSAYILAN_UST.get(h["dil"], self.VARSAYILAN_UST["en"]).format(oyun=OYUN.kisa.upper())
        profil = self.klasor / "profil.jpg"
        return {"ad": ad, "kullanici": h.get("imza") or "", "ust": ust, "tik": bool(d.get("tik", False)),
                "profil": profil.exists() and bool(ad),
                "profil_yol": profil if (profil.exists() and ad) else None}

    def _durum_yaz(self, d: dict) -> None:
        self.durum_yolu.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    def _adaylar_elle(self) -> list[kesif.Kanal]:
        return [kesif.Kanal(p, a) for p in ("twitch", "kick") if self._platform_acik_mi(p) for a in self._liste(p)]

    def _oto_acik_mi(self) -> bool:
        return bool(self._durum_oku().get("oto", self.oto_acik))

    def _platform_acik_mi(self, ad: str) -> bool:
        return bool((self._durum_oku().get("platform") or {}).get(ad, True))

    async def _tara(self, adet: int) -> list[tuple[kesif.Kanal, int]]:
        """Açık platformlarda şu an yayında olan GTA 6 yayınlarını bul (en çok izlenen önce)."""
        secili = {a: k for a, k in self.kesifler.items() if self._platform_acik_mi(a)}
        out: list[tuple[kesif.Kanal, int]] = []
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            sonuclar = await asyncio.gather(*(k.bul(c, adet) for k in secili.values()), return_exceptions=True)
        for ad, r in zip(secili, sonuclar):
            if isinstance(r, BaseException):
                log.warning("%s yayın bulma hatası: %r%s", ad, r,
                            " — config.yaml'a Twitch anahtarı girersen düzelir" if ad == "twitch" else "")
                continue
            log.info("%s: %d %s yayını bulundu", ad, len(r), OYUN.kisa)
            out += r
        out.sort(key=lambda x: -x[1])
        self.son_bulunan, self.son_tarama = out, time.time()
        return out

    def _yabanci_cevir(self) -> bool:
        """Başka dilde konuşan yayıncılar: altyazıyı İngilizceye çevirip kullan (True) ya da hiç alma (False)."""
        return bool(self.cfg.get("yabanci_dil_cevir", True))

    def _izinli_diller(self) -> set[str]:
        return {str(d).lower() for d in (self.cfg.get("izin_verilen_diller") or [h["dil"] for h in self._hesaplar()])}

    async def _adaylar_oto(self, adet: int) -> list[tuple[kesif.Kanal, int]]:
        bulunan = await self._tara(adet)
        if not self._oto_acik_mi():
            return []
        # sadece hesap açtığın dillerdeki yayınlar (dili bilinmeyenler de alınır)
        diller = self._izinli_diller()
        bulunan = [x for x in bulunan if (not x[0].dil or x[0].dil in diller) and x[0].anahtar not in self._yabanci]
        uygun = [x for x in bulunan if x[1] >= self.en_az_izleyici]
        # dil kotası: ör. {tr: 8} -> en az 8 Türkçe yayın listenin başına (Türkçe hesap için malzeme)
        kota = {str(k).lower(): int(v) for k, v in (self.cfg.get("dil_kotasi") or {"tr": 8}).items()}
        once, sonra = [], []
        sayac: dict[str, int] = {}
        for k, izl in uygun:
            if k.dil in kota and sayac.get(k.dil, 0) < kota[k.dil]:
                once.append((k, izl))
                sayac[k.dil] = sayac.get(k.dil, 0) + 1
            else:
                sonra.append((k, izl))
        # Türkçe yayın kotası dolmadıysa küçük Türkçe yayınları da al (izleyici sınırı olmadan)
        for k, izl in bulunan:
            if k.dil in kota and sayac.get(k.dil, 0) < kota[k.dil] and (k, izl) not in once:
                once.append((k, izl))
                sayac[k.dil] = sayac.get(k.dil, 0) + 1
        return once + sonra

    async def _youtube_elle(self) -> list[kesif.Kanal]:
        hs = self._liste("youtube") if self._platform_acik_mi("youtube") else []
        sonuc = await asyncio.gather(*(asyncio.to_thread(kesif.youtube_kanal_canli, h) for h in hs))
        return [k for k in sonuc if k]

    def _gunluk(self) -> int:
        """Her hesap için günde kaç paylaşım (Telegram /gunluk ile değişir)."""
        return int(self._durum_oku().get("gunluk") or self.cfg.get("gunluk_paylasim", 10))

    def _hedef_stok(self) -> int:
        return int(self.cfg.get("hedef_stok", max(15, self._gunluk() * 2)))

    def _ust_sinir(self) -> int:
        """Senin istediğin üst sınır (/sinir ya da config.yaml)."""
        return int(self._durum_oku().get("sinir") or self.cfg.get("ayni_anda_en_fazla_kanal", 8))

    def _sinir(self) -> int:
        """Gerçekte uygulanan sınır: bilgisayar kaldıramıyorsa otomatik düşürülür (saglik_ayari)."""
        ust = self._ust_sinir()
        return min(ust, self.etkin_sinir) if self.etkin_sinir else ust

    async def saglik_ayari(self) -> None:
        """Her 2 dk: kayıtların ne kadarı akıyor? Çoğu takılıyorsa izlenen yayın sayısını düşür,
        hepsi akıyorsa yavaşça artır. (Bilgisayar/internet aynı anda kaç yayın kaldırıyorsa o kadar.)"""
        while True:
            await asyncio.sleep(120)
            try:
                simdi = time.time()
                olgun = [iz for iz in self.izleyiciler.values()
                         if simdi - getattr(iz.kayit, "_baslama", simdi) > 150]
                if len(olgun) < 3:
                    continue
                saglikli = 0
                for iz in olgun:
                    d = await asyncio.to_thread(iz.kayit.durum)
                    if d["son_parca_sn"] is not None and d["son_parca_sn"] < 30 and d["parca"] >= 5:
                        saglikli += 1
                oran = saglikli / len(olgun)
                eski = self._sinir()
                if oran < 0.7:
                    self.etkin_sinir = max(3, min(eski, len(self.izleyiciler)) - 2)
                elif oran >= 0.9 and self.etkin_sinir and self.etkin_sinir < self._ust_sinir():
                    self.etkin_sinir += 2
                if self._sinir() != eski:
                    log.info("kayıtların %%%d'i akıyor → aynı anda izlenen yayın: %d → %d", int(oran * 100),
                             eski, self._sinir())
                    if self._sinir() < eski:
                        try:
                            await self.bot.mesaj(f"⚙️ Bilgisayar {eski} yayını aynı anda kaldıramıyor (kayıtların "
                                                 f"%{int(oran * 100)}'i akıyor). İzlenen yayın {self._sinir()}'e "
                                                 f"düşürüldü; düzelince kendisi artırır.")
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                log.exception("sağlık ayarı hatası")

    async def yonetici(self) -> None:
        while True:
            en_fazla = self._sinir()
            try:
                # sınır düşürüldüyse fazlaları bırak (önce otomatik bulunanlar)
                fazla = len(self.izleyiciler) - en_fazla
                if fazla > 0:
                    sirali = sorted(self.izleyiciler.items(),
                                    key=lambda x: (not x[1].oto, x[1].kanal.izleyici))   # önce otomatik + küçük
                    for anahtar, _ in sirali[:fazla]:
                        await self._birak(anahtar)
                        self._kapali.pop(anahtar, None)
                # ölenleri temizle / yeniden başlat
                for anahtar, iz in list(self.izleyiciler.items()):
                    if not iz.kayit.calisiyor_mu():
                        canli = await asyncio.to_thread(kesif.yayinda_mi, iz.kanal)
                        if canli and not self.duraklat:
                            log.info("kayıt yeniden başlatılıyor: %s", anahtar)
                            await self._kayit_yenile(iz)
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
                        # aynı yayıncı aynı yayını hem Twitch'te hem Kick'te açabiliyor: bir kez izle
                        izlenen_adlar = {_ad_anahtar(iz.kanal) for iz in self.izleyiciler.values()}
                        if _ad_anahtar(k) in izlenen_adlar:
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
                        try:   # bir yayında sorun çıkarsa diğerleri yine başlasın
                            await self._baslat(k, oto)
                        except Exception as e:  # noqa: BLE001
                            log.warning("%s izlenemedi (%r), 5 dk sonra tekrar denenecek", k.anahtar, e)
                            self._kapali[k.anahtar] = time.time()
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
        kalite = YENI_KALITE if not kl.get("kalite_zorla") else (kl.get("kalite") or YENI_KALITE)
        kayit = Kaydedici(url, self._tampon_kok() / k.anahtar.replace(":", "_"),
                          kalite, int(kl.get("tampon_sn", 240)))
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
            try:
                if int(time.time()) % 15 == 0:
                    await asyncio.to_thread(iz.kayit.temizle)
                    sinir = time.time() - iz.kayit.tampon
                    while iz.chat_log and iz.chat_log[0][0] < sinir:
                        iz.chat_log.popleft()
                if self.duraklat:
                    continue
                # kayıt koptuysa hemen (en fazla dakikada bir) yeniden başlat: boşluk kısa kalsın, klip kesilebilsin
                if int(time.time()) % 5 == 0 and time.time() - iz.son_yenileme > 60 and (
                        not iz.kayit.calisiyor_mu() or iz.kayit.takildi_mi()):
                    if iz.kayit.calisiyor_mu():
                        log.info("%s kaydı takıldı (yeni parça gelmiyor), yeniden başlatılıyor", iz.kanal.anahtar)
                    iz.son_yenileme = time.time()
                    try:
                        await self._kayit_yenile(iz)
                    except Exception as e:  # noqa: BLE001
                        log.warning("kayıt yeniden başlatılamadı (%s): %r", iz.kanal.anahtar, e)
                # yayın gerçekte başka dilde mi? (ör. dilini "İngilizce" seçmiş Arapça yayın) — chat'ten anla
                if (not self._yabanci_cevir() and iz.oto and int(time.time()) % 60 == 0
                        and len(iz.chat_log) >= 40):
                    yd = yazi_dili([m for _, _, m in list(iz.chat_log)[-150:]])
                    if yd and yd not in self._izinli_diller():
                        log.info("%s aslında %s konuşulan bir yayın (chat'e göre), bırakılıyor", iz.kanal.anahtar, yd)
                        self._yabanci.add(iz.kanal.anahtar)
                        # ayrı görev: _birak bu döngünün kendi görevini de iptal eder
                        asyncio.create_task(self._birak(iz.kanal.anahtar))
                        return
                iz.algila.kat = self.dinamik_kat
                s = iz.algila.kontrol(time.time())
                if s:
                    self._spike_gecmisi.append(time.time())
                    butce = self._saatlik_butce()
                    son_saat = [t for t in self._kabul_gecmisi if t > time.time() - 3600]
                    if len(son_saat) >= butce and s.kat < self.dinamik_kat * 1.8:
                        self.sayac["kotada"] += 1
                        log.info("chat patladı ama bu saatin klip kotası dolu (%d), sadece çok güçlü anlar alınıyor: %s",
                                 butce, iz.kanal.anahtar)
                        continue
                    if iz.oto and not self._yabanci_cevir():
                        yd = yazi_dili([m for _, _, m in list(iz.chat_log)[-200:]])
                        if yd and yd not in self._izinli_diller():
                            log.info("%s chat'i %s, bırakılıyor", iz.kanal.anahtar, yd)
                            self._yabanci.add(iz.kanal.anahtar)
                            asyncio.create_task(self._birak(iz.kanal.anahtar))
                            return
                    son = [m for t, _, m in list(iz.chat_log) if t >= time.time() - 12]
                    tepki_o = sum(1 for m in son if mesaj_puani(m)[0] > 1
                                  and mesaj_puani(m)[1] not in ("w", "gg", "?", "??", "???")) / max(1, len(son))
                    klip_n = sum(1 for m in son if mesaj_puani(m)[1] == "clip")
                    if tepki_o < 0.15 and klip_n < 2:
                        # chat hızlandı ama gülen/şaşıran yok (abone yağmuru, spam, oylama): klip yapma
                        self.sayac["zayif"] = self.sayac.get("zayif", 0) + 1
                        log.info("chat hızlandı ama tepki yok (%s, gülme %%%d), atlandı", iz.kanal.anahtar, int(tepki_o * 100))
                        continue
                    if iz.kayit.durum()["parca"] < 4:
                        log.info("chat patladı ama %s kaydı henüz hazır değil (görüntü gelmiyor), atlandı",
                                 iz.kanal.anahtar)
                        self.sayac["kayitsiz"] = self.sayac.get("kayitsiz", 0) + 1
                        continue
                    log.info("💥 chat patladı: %s (%.0f puan, normalin %.1f katı) %s",
                             iz.kanal.anahtar, s.puan, s.kat, s.kelimeler)
                    self.sayac["patlama"] += 1
                    asyncio.create_task(self._kes(iz, s))

            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  — bir yayının kontrolü sessizce ölmesin
                log.exception("%s kontrolünde hata (devam ediliyor)", iz.kanal.anahtar)

    def _saatlik_butce(self) -> int:
        # yayınlar günde ~12 saat yoğun: günlük hedefi saatlere böl
        return max(3, round(int(self.cfg.get("hedef_gunluk_klip", 60)) / 12))

    async def hiz_ayari(self) -> None:
        """Her 20 dk: çok klip çıkıyorsa eşiği yükselt, hiç çıkmıyorsa düşür (günde ~hedef kadar klip)."""
        a = self.cfg.get("algilama") or {}
        alt, ust = float(a.get("en_dusuk_kat", 2.0)), float(a.get("en_yuksek_kat", 8.0))
        while True:
            await asyncio.sleep(1200)
            if not self.izleyiciler or self.duraklat:
                continue
            simdi = time.time()
            self._spike_gecmisi = [t for t in self._spike_gecmisi if t > simdi - 3600]
            self._kabul_gecmisi = [t for t in self._kabul_gecmisi if t > simdi - 6 * 3600]
            n, butce = len(self._spike_gecmisi), self._saatlik_butce()
            eski = self.dinamik_kat
            if n > butce * 3:
                self.dinamik_kat = min(ust, self.dinamik_kat + 0.5)
            elif n < butce * 0.5:
                self.dinamik_kat = max(alt, self.dinamik_kat - 0.25)
            if self.dinamik_kat != eski:
                log.info("klip eşiği ayarlandı: normalin %.2f → %.2f katı (son 1 saatte %d patlama, hedef ~%d)",
                         eski, self.dinamik_kat, n, butce)

    async def _kayit_yenile(self, iz: Izleyici) -> None:
        """Kopan kaydı, son dakikaları silmeden yeniden başlat (program donmasın diye ayrı iş parçacığında)."""
        neden = iz.kayit.son_hata()
        if neden:
            log.info("%s kaydı koptu: %s", iz.kanal.anahtar, neden)
        if iz.kanal.platform == "kick":   # imzalı yayın linki yenilenmeli
            b = await asyncio.to_thread(kesif.kick_bilgi, iz.kanal.ad)
            if b and b.get("playback_url"):
                iz.kayit.url = "hls://" + b["playback_url"]
        # hiç görüntü gelmeden koptuysa: başka kalitede dene (bazı yayınlarda 720p akışı bozuk geliyor)
        if iz.kayit.durum()["parca"] < 2:
            iz.bos_baslama += 1
            yedek = {2: "best", 3: "480p,480p30,best", 4: "worst"}.get(iz.bos_baslama)
            if yedek:
                log.info("%s: görüntü gelmiyor, '%s' kalitesiyle deneniyor", iz.kanal.anahtar, yedek)
                iz.kayit.kalite = yedek
        else:
            iz.bos_baslama = 0
        await asyncio.to_thread(iz.kayit.yeniden_baslat)
        iz.son_yenileme = time.time()

    def _tampon_kok(self) -> Path:
        """Yayınların son dakikaları burada tutulur. OneDrive/Masaüstü dışında (Windows geçici klasörü):
        OneDrive her 4 sn'lik parçayı buluta yüklemeye çalışınca internet ve disk tıkanıyor."""
        import tempfile
        ozel = self.cfg.get("tampon_klasoru")
        if ozel:
            return Path(ozel)
        kok = Path(tempfile.gettempdir()) / "klipci_tampon"
        return kok if "onedrive" not in str(kok).lower() else Path("C:/klipci_tampon")

    @staticmethod
    def _kareler(is_: "Is") -> list[bytes]:
        """Patlama anının çevresinden 4 küçük kare (yapay zekâ neye bakıldığını görsün)."""
        an = is_.an if is_.an is not None else is_.sure * 0.6
        out = []
        for d in (-9, -4, 0, 3):
            t = max(0.0, min(is_.sure - 0.5, an + d))
            try:
                r = subprocess.run([arac("ffmpeg"), "-v", "error", "-ss", f"{is_.ofset + t:.2f}", "-i", str(is_.kaynak),
                                    "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "5", "-f", "image2pipe",
                                    "-c:v", "mjpeg", "-"], capture_output=True, timeout=30, creationflags=_PENCERESIZ)
                if r.stdout:
                    out.append(r.stdout)
            except Exception:  # noqa: BLE001
                pass
        return out

    def _secicilik(self) -> int:
        """Patlamaların yüzde kaçı video olsun (en iyileri). 100 = hepsi."""
        d = self._durum_oku()
        return int(d.get("kalite", self.cfg.get("kalite_yuzde", 50)))

    @staticmethod
    def _bos_an_mi(is_: "Is", ses_tepki: float, oyun_anlari: list, yuz_t: float = 0.0) -> str:
        """Yapay zekâsız (ücretsiz) 'boş an' kontrolü. Boş string = iyi an."""
        from .spike import mesaj_puani
        yakin = [m for t, _, m in is_.chat if is_.an - 3 <= t <= is_.an + 12]
        # "W", "gg", "?" komiklik göstermez; gülme/şok tepkileri sayılır
        sade = {"w", "gg", "?", "??", "???", "help"}
        gulme = sum(1 for m in yakin if mesaj_puani(m)[0] > 1 and mesaj_puani(m)[1] not in sade) / max(1, len(yakin))
        ara_sahne = (sum(v for _, v in oyun_anlari) / len(oyun_anlari)) if oyun_anlari else 0.0
        klip = sum(1 for m in yakin if mesaj_puani(m)[1] == "clip")
        # en az bir güçlü işaret lazım: chat gerçekten gülüyor / "clip" diyor / yayıncı bağırıyor ya da kamerada coşuyor
        # 1) chat gerçekten gülüyor/şaşırıyor ya da "clip" diyor  VE  2) yayıncı da tepki veriyor (bağırma / kamerada coşma)
        #    — chat çok güçlüyse (yarısından fazlası gülüyor) yayıncı sakin kalsa da olur
        chat_guclu = gulme >= 0.3 or klip >= 3
        yayinci_tepki = ses_tepki >= 6 or yuz_t >= 2.0 or gulme >= 0.5
        guclu = chat_guclu and yayinci_tepki
        if not guclu:
            return (f"güzel an işareti yok (chat gülme %{int(gulme * 100)}, 'clip' {klip}, "
                    f"ses +{ses_tepki:.0f} dB, yüz {yuz_t:.1f}x)")
        if ara_sahne >= 0.6 and gulme < 0.5:
            return f"çoğu oyunun ara sahnesi (%{int(ara_sahne * 100)}), chat'te pek gülme yok"
        return ""

    def _kalite_eler(self, skor: float, yz: int | None) -> str:
        """Boş string = geçti. Değilse elenme nedeni."""
        onceki = sorted(self._son_puanlar)
        self._son_puanlar.append(skor)
        if yz is not None and yz <= 3:
            return f"yapay zekâ 'boş an' dedi ({yz}/10)"
        yuzde = self._secicilik()
        # 2 saattir hiç klip geçmediyse süzgeci gevşet (stok boş kalmasın)
        if yuzde < 100 and len(onceki) >= 8 and time.time() - self._son_gecen < 7200:
            esik = onceki[min(len(onceki) - 1, int(len(onceki) * (100 - yuzde) / 100))]
            if skor < esik:
                return f"son kliplerin zayıf kısmında ({skor:.1f} < {esik:.1f})"
        self._son_gecen = time.time()
        return ""

    def _gecikme(self, k: kesif.Kanal) -> float:
        """Görüntü bize chat'ten kaç sn geç geliyor? Chat anında gelir, video HLS ile 6-12 sn geride kalır.
        Bunu hesaba katmazsak klip olay olmadan biter (komik an videonun sonunda kalır)."""
        g = self.cfg.get("gecikme_sn") or {}
        varsayilan = {"twitch": 6.0, "kick": 10.0, "youtube": 12.0}
        if isinstance(g, (int, float)):
            return float(g)
        return float(g.get(k.platform, varsayilan.get(k.platform, 8.0)))

    def _klip_araligi(self, s: Spike, gecikme: float = 0.0) -> tuple[float, float]:
        """Klibin başı ve sonu: olayın girişi (chat geç tepki verir) + chat'in ilk tepkisi.
        Sabit bir süre yok: chat coşmaya devam ettikçe _kes_ic klibi uzatır, sakinleşince biter."""
        kl = self.cfg.get("klip") or {}
        once, sonra = float(kl.get("once_sn", 18)), float(kl.get("sonra_sn", 8))
        once = min(once, 18.0)   # eski ayar (22) gereksiz uzun giriş yapıyordu
        return s.zaman + gecikme - once, s.tetik + gecikme + sonra

    @staticmethod
    def _chat_sicak_mi(iz: Izleyici) -> bool:
        simdi = time.time()
        try:
            return iz.algila._pencere_puani(simdi) >= max(iz.algila.en_az * 0.6, iz.algila.taban(simdi) * 1.6)
        except Exception:  # noqa: BLE001
            return False

    def _asama(self, tid: str, asama: str | None, kanal: kesif.Kanal | None = None) -> None:
        """Hazırlanan klibin aşamasını güncelle (None = bitti, listeden çıkar)."""
        if asama is None:
            self.isler.pop(tid, None)
            return
        bilgi = self.isler.setdefault(tid, {"t": time.time(), "ad": kanal.gorunen if kanal else tid,
                                            "platform": kanal.platform if kanal else ""})
        bilgi["asama"] = asama

    def _sira_metni(self) -> str:
        if not self.isler:
            return ("🎬 Şu an hazırlanan klip yok.\n"
                    f"Chat patlayınca burada görünür. (Bu oturumda {self.sayac['klip']} klip yapıldı.)")
        satir = [f"🎬 Hazırlanan klipler ({len(self.isler)})\n"]
        for i, b in enumerate(sorted(self.isler.values(), key=lambda x: x["t"]), 1):
            dk = int((time.time() - b["t"]) // 60)
            satir.append(f"{i}. {b['ad']} ({b['platform']}) — {b['asama']} · {dk} dk")
        satir.append("\nGenelde patlamadan 3-5 dk sonra telefonuna gelir.")
        return "\n".join(satir)

    async def _kes(self, iz: Izleyici, s: Spike) -> None:
        tid = f"{iz.kanal.anahtar}@{int(s.tetik)}"
        self._asama(tid, "⏺ kayıt sürüyor (klibin sonu bekleniyor)", iz.kanal)
        try:
            await self._kes_ic(iz, s, tid)
        finally:
            if self.isler.get(tid, {}).get("asama", "").startswith(("⏺", "✂️")):
                self._asama(tid, None)   # kuyruğa giremediyse listeden çıkar

    async def _kes_ic(self, iz: Izleyici, s: Spike, tid: str) -> None:
        g = self._gecikme(iz.kanal)
        bas, bit = self._klip_araligi(s, g)
        en_uzun = max(90.0, float((self.cfg.get("klip") or {}).get("en_uzun_sn", 90)))
        await asyncio.sleep(max(0.0, bit - time.time()))
        # komiklik sürdükçe (chat hâlâ coşuyor) klip uzar; sakinleşince birkaç saniye tepki payı bırakıp biter
        uzadi = False
        while bit - bas + 3 <= en_uzun and self._chat_sicak_mi(iz):
            bit = max(bit + 3, time.time() + g + 3)   # chat şu an coşuyorsa görüntüde bu an g sn sonra
            uzadi = True
            await asyncio.sleep(max(0.0, bit - time.time()))
        if uzadi:
            bit += 3
            await asyncio.sleep(max(0.0, bit - time.time()))
        await asyncio.sleep(PARCA_SN * 2 + 1)
        self._asama(tid, "✂️ kesiliyor")
        kid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + iz.kanal.ad
        hedef = self.klasor / "_is" / f"{kid}.ts"
        try:
            sonuc = await asyncio.to_thread(iz.kayit.kes, bas, bit, hedef, s.zaman + g)
        except Exception as e:  # noqa: BLE001
            log.warning("kesme başarısız: %s", e)
            self.sayac["kesilemedi"] += 1
            self.son_sorun = f"kesme başarısız: {e}"[:150]
            return
        if not sonuc:
            neden = iz.kayit.son_neden or "bilinmiyor"
            log.warning("klip kesilemedi (%s): %s", iz.kanal.anahtar, neden)
            self.sayac["kesilemedi"] += 1
            self.son_sorun = f"{iz.kanal.gorunen}: {neden}"[:300]
            return
        bas, bit = sonuc[2], sonuc[3]   # kayıtta boşluk varsa klip kısaltılmış olabilir
        self._kabul_gecmisi.append(time.time())   # kota sadece gerçekten kesilen klipten düşer
        if self.cfg.get("hazirlaniyor_bildirimi", True):
            try:
                await self.bot.mesaj(f"🎬 Klip hazırlanıyor: {iz.kanal.gorunen} ({iz.kanal.platform}) — "
                                     f"chat normalin {s.kat:.1f} katı. 2-3 dk içinde gelir (/sira)")
            except Exception:  # noqa: BLE001
                pass
        # chat'i görüntüyle eşle: viewers'ın t anındaki mesajı, bizim kayıtta t+g anına denk gelir
        chat = [(t + g - bas, k, m) for t, k, m in list(iz.chat_log) if bas <= t + g <= bit]
        esik = int(self.cfg.get("yuz_icin_en_az_izleyici", 2000))
        buyuk = (not iz.oto) or iz.kanal.izleyici >= esik   # senin eklediklerin büyük sayılır
        self._asama(tid, f"⏳ sırada (önünde {self.kuyruk.qsize()} klip)")
        await self.kuyruk.put(Is(iz.kanal, s, sonuc[0], sonuc[1], bit - bas, chat, buyuk, max(0.0, s.zaman + g - bas),
                                 tid))

    # ---------- kurgu işçisi ----------
    async def isci(self) -> None:
        while True:
            is_ = await self.kuyruk.get()
            self.sayac["isleniyor"] += 1
            try:
                await self._isle(is_)
            except Exception as e:  # noqa: BLE001
                log.exception("klip işlenemedi")
                self.sayac["hata"] += 1
                self.son_sorun = f"klip işlenemedi: {e!r}"[:150]
            finally:
                self.sayac["isleniyor"] -= 1
                is_.kaynak.unlink(missing_ok=True)
                self._asama(is_.takip, None)

    async def _isle(self, is_: Is) -> None:
        kid = is_.kaynak.stem

        self._asama(is_.takip, "🔎 inceleniyor: yüz, ses, altyazı")
        # 1) analizler aynı anda: yüz kamerası + aksiyon, ses, konuşma
        alt_not: list[str] = []   # altyazı neden yok / ne oldu (Telegram'da klibin altında yazar)

        async def konusma():
            if not self.yaziya:
                alt_not.append("altyazı ayardan kapalı")
                return None
            if not self.yaziya.hazir:
                # model hazır değilse BEKLEME: klip altyazısız çıksın, sıra tıkanmasın
                alt_not.append(f"altyazı aracı hazır değil ({self.yaziya.durum})")
                return None
            wav = is_.kaynak.with_suffix(".wav")
            try:
                await asyncio.to_thread(ses_cikar, is_.kaynak, is_.ofset, is_.sure, wav)
                return await asyncio.wait_for(asyncio.to_thread(self.yaziya.coz, wav, is_.kanal.dil), 240)
            except asyncio.TimeoutError:
                alt_not.append(f"altyazı aracı yetişmedi ({self.yaziya.durum})")
                return None
            except Exception as e:  # noqa: BLE001
                log.warning("altyazı çıkarılamadı (klip altyazısız yapılacak): %r", e)
                alt_not.append(f"altyazı hatası: {e!r}"[:160])
                return None
            finally:
                wav.unlink(missing_ok=True)

        analiz, ses, cozum, oyun_anlari = await asyncio.gather(
            asyncio.to_thread(yuz.analiz_et, is_.kaynak, is_.ofset, is_.sure),
            asyncio.to_thread(puan.ses_ozellikleri, is_.kaynak, is_.ofset, is_.sure),
            konusma(),
            asyncio.to_thread(oyun_altyazi_anlari, is_.kaynak, is_.ofset, is_.sure))
        # meme'ler için oyun görüntüsünün ham hâlini sakla (3 gün)
        try:
            ham = self.klasor / "ham" / f"{kid}.mp4"
            ham.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(subprocess.run, [
                arac("ffmpeg"), "-y", "-v", "error", "-ss", f"{is_.ofset:.2f}", "-t", f"{is_.sure:.2f}",
                "-i", str(is_.kaynak), "-c", "copy", str(ham)], check=True, creationflags=_PENCERESIZ)
        except Exception as e:  # noqa: BLE001
            log.debug("ham saklanamadı: %r", e)
        facecam = analiz.facecam if (self.cfg.get("yuz_kamerasi", True) and is_.buyuk) else None
        if analiz.facecam and not is_.buyuk:
            log.info("küçük yayıncı (%s izleyici): yüzü kullanılmadı", is_.kanal.izleyici)
        segler = cozum.segmentler if cozum else []
        if cozum is None and not alt_not:
            alt_not.append(f"altyazı aracı çalışmadı ({self.yaziya.durum if self.yaziya else 'kapalı'})")
        elif cozum is not None and not segler:
            alt_not.append("yayıncının konuşması duyulmadı")
        # yayıncı aslında hesaplarının dilinde konuşmuyorsa (ör. Arapça) klip yapma
        if cozum and cozum.asil_dil and cozum.asil_dil != cozum.dil:
            alt_not.append(f"yayıncı {cozum.asil_dil} konuşuyor, İngilizceye çevrildi")
        if (not self._yabanci_cevir() and cozum and cozum.guven >= 0.75 and len(segler) >= 2
                and (cozum.asil_dil or cozum.dil) not in self._izinli_diller()):
            log.info("klip elendi: yayıncı %s konuşuyor (hesapların: %s) — %s", cozum.dil,
                     ",".join(sorted(self._izinli_diller())), kid)
            self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
            if is_.kanal.platform != "youtube":
                self._yabanci.add(is_.kanal.anahtar)
            return
        kaynak_dil = cozum.dil if cozum else ""
        zoom = float((self.cfg.get("klip") or {}).get("zoom", 1.3))
        ce = self.cfg.get("chat_ekrani") or {}
        ses_tepki = await asyncio.to_thread(puan.an_tepkisi, is_.kaynak, is_.ofset, is_.sure, is_.an)
        duran = await asyncio.to_thread(hareketsiz_oran, is_.kaynak, is_.ofset, is_.sure, analiz.facecam)
        yuz_t = await asyncio.to_thread(yuz_tepkisi, is_.kaynak, is_.ofset, is_.sure, analiz.facecam, is_.an)
        if duran >= 0.5:   # harita / menü / ayarlar: kimse izlemez
            log.info("klip elendi: oyun ekranı zamanın %%%d'inde duruyor (menü/harita) — %s", int(duran * 100), kid)
            self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
            return
        chat_pop = (chat_sec(is_.chat, is_.sure, 1, float(ce.get("sure_sn", 1.8)),
                             en_fazla=int(ce.get("en_fazla_mesaj", 5)), an=is_.an)
                    if ce.get("acik", True) else [])
        en_dusuk = float(self.cfg.get("en_dusuk_puan", 0))

        kareler = await asyncio.to_thread(self._kareler, is_) if self.yazar.client else []
        for h in self._hedef_hesaplar(kaynak_dil or is_.kanal.dil):
            dil, ad = h.get("dil", "tr"), h.get("ad", "TR")
            hid = f"{kid}_{ad}"
            self._asama(is_.takip, f"✍️ yazılar hazırlanıyor ({ad})")
            veri = await asyncio.to_thread(self.yazar.yaz, dil, is_.kanal.gorunen, is_.kanal.platform, segler,
                                           kaynak_dil, is_.spike.ornek_mesajlar, is_.spike.kelimeler, kareler)
            # sadece YAYINCININ konuşması altyazı olur (oyundaki karakterler, ara sahneler, radyo değil)
            sec = veri.get("yayinci_konusmasi")
            if isinstance(sec, list):
                secili = {i for i in sec if isinstance(i, int) and 0 <= i < len(segler)}
            else:   # ücretsiz yol: o an ekranda oyunun kendi altyazısı varsa konuşan oyundaki karakterdir
                secili = {i for i, (b, e, _) in enumerate(segler) if not oyun_konusmasi_mi(b, e, oyun_anlari)}
                if len(secili) < len(segler):
                    log.info("oyundan gelen %d konuşma altyazıya alınmadı", len(segler) - len(secili))
                    alt_not.append(f"{len(segler) - len(secili)}/{len(segler)} konuşma oyundaki karakterlere ait, yazılmadı")
            if veri.get("altyazi") and len(veri["altyazi"]) == len(segler) and kaynak_dil != dil:
                alt = segment_parcala([(b, e, t) for i, ((b, e, _), t) in enumerate(zip(segler, veri["altyazi"]))
                                       if i in secili])
            elif cozum and (kaynak_dil == dil or not veri.get("altyazi")):
                # aynı dil ya da çeviri yok: konuşma kendi dilinde, kelime kelime yazılır
                araliklar = [(segler[i][0] - 0.05, segler[i][1] + 0.05) for i in secili]
                alt = kelime_parcala([k for k in cozum.kelimeler
                                      if any(b <= (k.bas + k.bit) / 2 <= e for b, e in araliklar)])
            else:
                alt = segment_parcala([(b, e, t) for i, ((b, e, _), t) in
                                       enumerate(zip(segler, veri.get("altyazi", []))) if i in secili])
            # altyazı doğal yazımıyla kalır ("Oh my god"), büyük harfe çevrilmez

            # 2) puan (senin beğenilerine göre ayarlanır)
            oz = puan.ozellik_cikar(is_.spike.kat, is_.chat, is_.sure, ses, analiz.aksiyon,
                                    sum(len(t.split()) for _, _, t in segler), bool(facecam),
                                    veri.get("puan") if self.yazar.client else None)
            skor, neden = self.ogrenci.puanla(hid, is_.kanal.gorunen.lower(), oz)
            hedef_kok = "bekleyen" if skor >= en_dusuk else "dusuk_puan"
            # sadece iyi anlar video olur: yapay zekâ "boş an" dediyse ya da son kliplerin zayıf yarısındaysa atla
            yz = veri.get("puan") if self.yazar.client else None
            elendi = self._kalite_eler(skor, yz) or (
                "" if yz is not None else self._bos_an_mi(is_, ses_tepki, oyun_anlari, yuz_t))
            if elendi:
                log.info("klip elendi (%s): %s — puan %.1f", elendi, hid, skor)
                self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
                self._asama(is_.takip, None)
                continue

            # 3) video
            klasor = self.klasor / hedef_kok / hid
            klasor.mkdir(parents=True, exist_ok=True)
            ass = klasor / "yazi.ass"
            an = is_.an if self.cfg.get("yakinlasma", True) else None
            # yüz varsa: üstte yüz, altta oyun. Yoksa: tweet tarzı (ayardan "tek" de seçilebilir)
            # yüz varsa: varsayılan "pip" (oyun tam ekran, kamera sol üstte kutu); "yuz" = üstte kamera altta oyun
            duzen = (str(self.cfg.get("yuzlu_duzen", "pip")) if facecam
                     else str(self.cfg.get("yuzsuz_duzen", "tweet")))
            tepki = None
            if self.cfg.get("tepki_yazisi", True):
                tepki = (is_.an, tepki_yazisi(is_.spike.kelimeler, is_.spike.ornek_mesajlar, dil, hid))
            mp4 = klasor / f"{hid}.mp4"
            try:
                self._asama(is_.takip, f"🎞 video kurgulanıyor ({ad})")
                if duzen == "tweet":
                    sayfa = self._sayfa(h)
                    ass_yaz(ass, is_.sure, veri.get("baslik", ""), f"🎥 {is_.kanal.kredi}", h.get("imza", ""), alt,
                            [], "tweet", sayfa, tepki)
                    await asyncio.to_thread(tweet_video, is_.kaynak, is_.ofset, is_.sure, mp4, ass,
                                            sayfa.get("profil_yol"), an)
                else:
                    ass_yaz(ass, is_.sure, veri.get("baslik", ""), f"🎥 {is_.kanal.kredi}", h.get("imza", ""), alt,
                            [] if duzen == "pip" else chat_pop, duzen, None, tepki)
                    await asyncio.to_thread(dikey_video, is_.kaynak, is_.ofset, is_.sure, mp4, ass, zoom, facecam,
                                            an, bool(self.cfg.get("ilerleme_cubugu", False)), duzen)
            finally:
                ass.unlink(missing_ok=True)
            if not await asyncio.to_thread(video_saglam_mi, mp4):
                log.warning("çıkan video boş/bozuk, atlandı: %s", hid)
                shutil.rmtree(klasor, ignore_errors=True)
                continue
            metin = paylasim_metni(veri, is_.kanal, dil)
            pm = platform_metinleri(veri, is_.kanal, dil)
            (klasor / "aciklama.txt").write_text(
                f"INSTAGRAM:\n{pm['instagram']}\n\nTIKTOK:\n{pm['tiktok']}\n\n"
                f"YOUTUBE BAŞLIK:\n{pm['youtube_baslik']}\n\nYOUTUBE AÇIKLAMA:\n{pm['youtube_aciklama']}\n",
                encoding="utf-8")
            (klasor / "aciklama.json").write_text(json.dumps(pm, ensure_ascii=False, indent=1), encoding="utf-8")
            sira, toplam = self.ogrenci.sira(hid)
            (klasor / "bilgi.json").write_text(json.dumps({
                "kanal": is_.kanal.anahtar, "yayinci": is_.kanal.gorunen, "platform": is_.kanal.platform,
                "hesap": ad, "dil": dil, "puan": skor, "neden": neden, "ozellikler": oz,
                "facecam": bool(facecam), "chat_kat": round(is_.spike.kat, 1), "kelimeler": is_.spike.kelimeler,
                "transkript": [t for _, _, t in segler],
                "altyazi_notu": "; ".join(dict.fromkeys(alt_not)) or (f"{len(alt)} satır altyazı" if alt else "")}, ensure_ascii=False, indent=1), encoding="utf-8")
            self.sayac["klip"] += 1
            if hedef_kok == "dusuk_puan":
                log.info("düşük puan (%.1f < %.1f), Telegram'a yollanmadı: %s", skor, en_dusuk, hid)
                continue
            log.info("✅ klip hazır: %s (puan %.1f)", mp4, skor)
            self._asama(is_.takip, "📤 Telegram'a gönderiliyor")
            await self._gonder(klasor)

    def _baslik_metni(self, bilgi: dict, metin: str, hid: str) -> str:
        sira, toplam = self.ogrenci.sira(hid)
        yildiz = "🔥" if bilgi.get("puan", 0) >= 7.5 else "⭐" if bilgi.get("puan", 0) >= 5 else "▫️"
        ust = (f"[{bilgi.get('hesap', '')}] {yildiz} {bilgi.get('puan', '?')}/10 — {bilgi.get('yayinci', '')} "
               f"({bilgi.get('platform', '')})")
        if toplam > 1:
            ust += f" · son 24 saatin {sira}./{toplam}"
        if bilgi.get("neden"):
            ust += f"\n💡 {bilgi['neden']}"
        if bilgi.get("altyazi_notu"):
            ust += f"\n📝 {bilgi['altyazi_notu']}"
        return ust + "\n\n" + metin

    async def _gonder(self, klasor: Path) -> bool:
        """Klibi Telegram'a yolla. Olmazsa klasörde bekler, internet gelince tekrar denenir."""
        isaret = klasor / ".gonderildi"
        if isaret.exists():
            return True
        # aynı klip aynı anda iki kez yollanmasın (ilk gönderim sürerken tekrar deneme döngüsü de görebiliyor)
        if klasor.name in self._gonderiliyor:
            return True
        self._gonderiliyor.add(klasor.name)
        try:
            return await self._gonder_ic(klasor, isaret)
        finally:
            self._gonderiliyor.discard(klasor.name)

    async def _gonder_ic(self, klasor: Path, isaret: Path) -> bool:
        mp4s = list(klasor.glob("*.mp4"))
        if not mp4s or not self.bot.chat_id:
            return False
        try:
            bilgi = json.loads((klasor / "bilgi.json").read_text(encoding="utf-8"))
            metin = json.loads((klasor / "aciklama.json").read_text(encoding="utf-8")).get("instagram", "")
        except (OSError, ValueError):
            bilgi, metin = {}, ""
        try:
            await self.bot.video_gonder(mp4s[0], self._baslik_metni(bilgi, metin, klasor.name), klasor.name)
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram'a gönderilemedi, sonra tekrar denenecek: %r", e)
            return False
        isaret.write_text("1")
        return True

    async def gonderici(self) -> None:
        """İnternet kopunca gönderilemeyen klipleri her dakika tekrar dener."""
        while True:
            await asyncio.sleep(60)
            for k in sorted((self.klasor / "bekleyen").glob("*")):
                if k.is_dir() and not (k / ".gonderildi").exists() and (k / "bilgi.json").exists():
                    if not await self._gonder(k):
                        break

    # ---------- telegram geri bildirim ----------
    async def _onay(self, kid: str) -> str:
        await asyncio.to_thread(self.ogrenci.karar, kid, "onay")
        kaynak = self.klasor / "bekleyen" / kid
        if not kaynak.exists():
            raise RuntimeError("klip bulunamadı")
        hesap = kid.rsplit("_", 1)[-1]
        hedef = self.klasor / "hazir" / hesap / kid
        hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(kaynak), str(hedef))
        self.sayac["onay"] += 1
        n = len(self.plan.stok(hesap))
        hedef_n = self._hedef_stok()
        return f"📦 {hesap} stok: {n}/{hedef_n}" + (" ✅ yarın için yeterli" if n >= hedef_n else "")

    async def _sil(self, kid: str) -> None:
        await asyncio.to_thread(self.ogrenci.karar, kid, "sil")
        shutil.rmtree(self.klasor / "bekleyen" / kid, ignore_errors=True)

    YARDIM = (
        "📋 TÜM KOMUTLAR  (bu listeyi her zaman /info ile açabilirsin)\n\n"
        "📊 DURUM\n"
        "/durum — neler izleniyor, kaç klip çıktı\n"
        "/sira — şu an hazırlanan klipler ve hangi aşamada oldukları\n"
        "/kayit — her yayının kaydı çalışıyor mu (sorun ararken)\n"
        "/plan — bugünün paylaşım saatleri\n"
        "/stok — hesaplarda kaç video hazır\n"
        "/istatistik — neyi sevdiğini ne kadar öğrendim\n\n"
        "🎮 YAYINCILAR\n"
        "/yayinlar — şu an açık yayınlar, dokunarak seç ⭐ / ⛔\n"
        "/twitch kaicenat — Twitch yayıncısı ekle (birden çok: /twitch kaicenat xqc)\n"
        "/kick adinross — Kick yayıncısı ekle\n"
        "/youtube @IShowSpeed — YouTube kanalı ekle\n"
        "   (ya da direkt yayının linkini at)\n"
        "/cikar twitch xqc — listeden çıkar\n"
        "/yasakla xqc — bu yayıncıyı asla klipleme\n"
        "/yasak_kaldir xqc — yasağı kaldır\n"
        "/liste — eklediklerin ve yasaklılar\n"
        "/platform — Twitch / Kick / YouTube aç-kapat\n"
        "/sinir 25 — aynı anda kaç yayın izlensin\n"
        "/kalite 50 — chat patlamalarının en iyi yüzde kaçı video olsun (100 = hepsi)\n\n"
        "🎬 VİDEOLAR\n"
        "/gunluk 10 — her hesap için günde kaç paylaşım\n"
        "/meme — şimdi meme videosu yap (her gün 10:00'da kendisi de yapar)\n"
        "/isim @kullaniciadin — videoların altındaki isim\n"
        "/ad Adın — tweet tarzı videolarda görünen ad\n"
        "/ustyazi BAŞLIK — tweet tarzı videoların büyük başlığı\n"
        "📷 Profil fotoğrafı: bota fotoğraf at, açıklamasına /profil yaz\n"
        "/hesap — TR / EN hesaplarını aç-kapat\n\n"
        "⚙️ PROGRAM\n"
        "/guncelle — yeni sürüm varsa indirip kur\n"
        "/duraklat — kliplemeyi durdur\n"
        "/devam — tekrar başlat\n"
        "/info — bu liste")

    async def _komut(self, metin: str) -> str:
        parca = metin.strip().split(maxsplit=1)
        komut = parca[0].lower().split("@")[0] if parca[0].startswith("/") else ""
        arg = parca[1] if len(parca) > 1 else ""
        if not komut:   # komutsuz mesaj: içinde yayın linki varsa ekle
            return await self._ekle(metin) if kesif.kanal_coz(metin) and "." in metin else ""
        if komut in ("/info", "/komutlar", "/yardim", "/yardım", "/help"):
            return self.YARDIM
        if komut in ("/kayit", "/kayıt"):
            if not self.izleyiciler:
                return "Şu an izlenen yayın yok."
            satir = ["📼 Kayıt durumu (her yayın)\n"]
            for iz in list(self.izleyiciler.values())[:30]:
                d = iz.kayit.durum()
                ikon = "🟢" if d["calisiyor"] and d["parca"] >= 2 else "🟡" if d["calisiyor"] else "🔴"
                ek = f"son parça {d['son_parca_sn']} sn önce" if d["son_parca_sn"] is not None else "parça yok"
                if d["ad_saat_farki"] is not None and abs(d["ad_saat_farki"] - (d["son_parca_sn"] or 0)) > 60:
                    ek += f" ⚠️ dosya saati {d['ad_saat_farki']} sn farklı"
                rk = iz.kayit.reklam_sayisi()
                if rk:
                    ek += f", 📺 {rk} reklam"
                satir.append(f"{ikon} {iz.kanal.gorunen} ({iz.kanal.platform}): {d['parca']} parça, {ek}"
                             + (f" — hata: {d['hata'][:80]}" if d["hata"] else ""))
            satir.append("\n🟢 kayıt var · 🟡 çalışıyor ama parça yok · 🔴 kayıt durmuş")
            if self.izleyiciler:
                satir.append(f"Klasör: {next(iter(self.izleyiciler.values())).kayit.klasor.parent}")
            return "\n".join(satir)
        if komut in ("/sira", "/sıra", "/kuyruk"):
            return self._sira_metni()
        if komut == "/durum":
            satir = []
            for k, iz in self.izleyiciler.items():
                satir.append(f"• {iz.kanal.gorunen} ({iz.kanal.platform})" + (" 🤖" if iz.oto else " ⭐"))
            kanal = "\n".join(satir) or "— (şu an açık yayın yok)"
            return (f"{'⏸ DURAKLATILDI' if self.duraklat else '▶ Çalışıyor'}\n"
                    f"İzlenen yayınlar ({len(self.izleyiciler)}/{self._sinir()}"
                    + (f", senin sınırın {self._ust_sinir()} ama bilgisayar şu an bu kadarını kaldırıyor"
                       if self._sinir() < self._ust_sinir() else ", /sinir ile değiştir") + f"):\n{kanal}\n"
                    f"⭐ = senin eklediğin, 🤖 = otomatik bulunan\n\n"
                    f"⏱ {int((time.time() - self.basladi) / 60)} dakikadır açık\n"
                    f"💥 Chat patlaması: {self.sayac['patlama']} (kota dolu diye atlanan: {self.sayac['kotada']})\n"
                    f"🎬 Yapılan klip: {self.sayac['klip']} · zayıf diye elenen: {self.sayac['elenen']} "
                    f"(en iyi %{self._secicilik()} video oluyor, /kalite) · şu an hazırlanan: "
                    f"{self.sayac['isleniyor'] + self.kuyruk.qsize()}\n"
                    f"⚠️ Kesilemeyen: {self.sayac['kesilemedi']} · hata: {self.sayac['hata']}\n"
                    f"✅ Onayladığın: {self.sayac['onay']}\n"
                    + (f"😐 Chat hızlandı ama gülen yok diye atlanan: {self.sayac['zayif']}\n"
                       if self.sayac.get("zayif") else "")
                    + (f"📵 Kaydı hazır olmadığı için atlanan patlama: {self.sayac['kayitsiz']}\n"
                       if self.sayac.get("kayitsiz") else "")
                    + f"Altyazı: {self.yaziya.durum if self.yaziya else 'kapalı'}"
                    + (f"\nSon sorun: {self.son_sorun}" if self.son_sorun else "")
                    + ("\n\nℹ️ İlk klip genelde 15-30 dk içinde gelir (chat'in gerçekten patlaması lazım)."
                       if self.sayac["klip"] == 0 else ""))
        if komut in ("/yayinlar", "/yayınlar", "/sec", "/seç"):
            await self._yayin_menusu_gonder()
            return ""
        if komut == "/platform":
            await self.bot.butonlu(*self._platform_menusu())
            return ""
        if komut == "/kalite":
            if not arg.strip():
                return (f"Şu an chat patlamalarının en iyi %{self._secicilik()} kadarı video oluyor.\n"
                        f"Daha seçici: /kalite 30 · Daha çok video: /kalite 80 · Hepsi: /kalite 100")
            try:
                n = int(arg.strip().lstrip("%"))
            except ValueError:
                return "Sayı yaz: /kalite 50"
            if not 10 <= n <= 100:
                return "10 ile 100 arası bir sayı yaz."
            d = self._durum_oku()
            d["kalite"] = n
            self._durum_yaz(d)
            return f"✅ Artık en iyi %{n} video olacak." + (" (hepsi)" if n == 100 else "")
        if komut in ("/sinir", "/sınır"):
            if not arg.strip():
                return (f"Üst sınır: {self._ust_sinir()} yayın. Şu an {self._sinir()} yayına izin var "
                        f"({len(self.izleyiciler)} tanesi açık). Kayıtlar akıcıysa kendisi artırır.\nDeğiştirmek için: /sinir 25")
            try:
                n = int(arg.strip())
            except ValueError:
                return "Sayı yaz: /sinir 25"
            if not 1 <= n <= 100:
                return "1 ile 100 arası bir sayı yaz."
            d = self._durum_oku()
            d["sinir"] = n
            self._durum_yaz(d)
            # hepsini birden açma: şu anki sayıdan devam, kayıtlar akıcıysa {n}'e kadar artar
            self.etkin_sinir = min(n, max(self.etkin_sinir or 6, 3))
            self._uyandir.set()
            not_ = "\n(40'ın üstü güçlü bilgisayar ister; kasarsa düşür.)" if n > 40 else ""
            return (f"✅ Artık aynı anda en fazla {n} yayın izlenecek.\n"
                    f"Şimdi {self.etkin_sinir} ile devam ediyor; kayıtlar akıcıysa birkaç dakikada bir 2 artar.{not_}")
        if komut in ("/ad", "/ustyazi", "/üstyazı", "/ustyazı"):
            parca = arg.split(maxsplit=1)
            if not parca:
                return ("Tweet tarzı videoların üst kısmı:\n/ad GTA 6 Anları — sayfa adı\n"
                        "/ustyazi GÜNÜMÜ GÜZELLEŞTİREN KLİPLER — büyük başlık\n"
                        "(sadece bir hesap için: /ustyazi en GTA 6 CLIPS THAT MADE MY DAY)\n"
                        "Profil fotoğrafı: bota fotoğraf at, açıklamasına /profil yaz.")
            hedef, metin = "*", arg.strip()
            if len(parca) == 2 and parca[0].upper() in {h["ad"] for h in self._hesaplar(hepsi=True)}:
                hedef, metin = parca[0].upper(), parca[1].strip()
            d = self._durum_oku()
            alan = "ad" if komut == "/ad" else "ust"
            sozluk = d.setdefault("sayfa", {}).setdefault(alan, {})
            if hedef == "*":
                sozluk.clear()
            sozluk[hedef] = metin
            self._durum_yaz(d)
            return f"✅ {'Sayfa adı' if alan == 'ad' else 'Üst başlık'}: “{metin}”" + ("" if hedef == "*" else f" ({hedef})")
        if komut in ("/guncelle", "/güncelle"):
            from . import guncelle as g
            var, yerel, uzak = await asyncio.to_thread(g.yeni_var_mi)
            if uzak is None:
                return "GitHub'a ulaşılamadı, sonra tekrar dene."
            if not var and arg.strip() != "zorla":
                return f"✅ En güncel sürüm kurulu ({yerel})."
            await self.bot.mesaj(f"⬇️ Yeni sürüm indiriliyor: {yerel} → {uzak} ...")
            try:
                n = await asyncio.to_thread(g.guncelle, {"baslat.bat"})
                await asyncio.to_thread(g.paketleri_kur)
            except Exception as e:  # noqa: BLE001
                return f"Güncelleme olmadı: {e!r}"
            await self.bot.mesaj(f"✅ Güncellendi ({n} dosya). Program yeniden başlıyor, 1 dk içinde geri gelir.")
            asyncio.get_running_loop().call_later(2, self._yeniden_baslat)
            return ""
        if komut == "/gunluk":
            if not arg.strip().isdigit():
                return (f"Şu an her hesap için günde {self._gunluk()} paylaşım planlanıyor "
                        f"({len(self._hesaplar())} hesap = günde ~{self._gunluk() * len(self._hesaplar())} video).\n"
                        f"Değiştirmek için: /gunluk 12")
            n = max(1, min(30, int(arg.strip())))
            d = self._durum_oku()
            d["gunluk"] = n
            self._durum_yaz(d)
            return f"✅ Her hesap için günde {n} paylaşım (toplam ~{n * len(self._hesaplar())}). Yarının planından itibaren geçerli."
        if komut == "/meme":
            n = await self.meme_uret(int(arg) if arg.strip().isdigit() else 2)
            return f"🎭 {n} meme yapıldı, onayına geldi." if n else \
                "Meme yapacak oyun görüntüsü yok henüz (önce birkaç klip çıkması lazım)."
        if komut == "/plan":
            return self._plan_metni()
        if komut == "/stok":
            return self._stok_metni()
        if komut == "/hesap":
            await self.bot.butonlu(*self._hesap_menusu())
            return ""
        if komut == "/isim":
            parca = arg.split()
            if not parca:
                return "Örnek: /isim @gta6klipleri   (sadece bir hesap için: /isim en @gta6clips)\nKaldırmak için: /isim sil"
            d = self._durum_oku()
            imza = d.setdefault("imza", {})
            hedef = "*"
            if len(parca) >= 2 and parca[0].upper() in {h["ad"] for h in self._hesaplar(hepsi=True)}:
                hedef, parca = parca[0].upper(), parca[1:]
            yeni = "" if parca[0].lower() in ("sil", "yok", "-") else parca[0]
            if yeni and not yeni.startswith("@"):
                yeni = "@" + yeni
            if hedef == "*":
                imza.clear()
            imza[hedef] = yeni
            self._durum_yaz(d)
            kim = "tüm hesaplar" if hedef == "*" else hedef
            return f"✅ {kim}: videonun altına " + (f"“{yeni}” yazılacak." if yeni else "isim yazılmayacak.")
        if komut in ("/istatistik", "/zevk"):
            return self.ogrenci.ozet()
        if komut in ("/twitch", "/kick", "/youtube", "/yt"):
            if not arg.strip():
                ornek = {"/twitch": "kaicenat", "/kick": "adinross"}.get(komut, "@IShowSpeed")
                return f"Örnek: {komut} {ornek}"
            platform = {"/yt": "youtube"}.get(komut, komut[1:])
            sonuc = []
            for ad in arg.replace(",", " ").split():   # birden çok isim: /twitch kaicenat xqc
                sonuc.append(await self._ekle(f"{platform} {ad}"))
            return "\n".join(sonuc)
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

    def _yeniden_baslat(self) -> None:
        """Kayıtları kapat, 3 koduyla çık: BASLAT.bat bunu görünce programı yeniden açar."""
        import os
        for iz in list(self.izleyiciler.values()):
            try:
                iz.kayit.durdur()
            except Exception:  # noqa: BLE001
                pass
        try:
            (self.kok / "klipci.pid").unlink(missing_ok=True)
        except OSError:
            pass
        os._exit(3)

    async def _profil_kaydet(self, veri: bytes) -> str:
        """Telegram'dan gelen fotoğrafı tweet tarzı videoların profil resmi yap."""
        hedef = self.klasor / "profil.jpg"
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_bytes(veri)
        return "✅ Profil fotoğrafı kaydedildi. Tweet tarzı videolarda yuvarlak olarak görünecek."

    # ---------- butonlu menüler ----------
    def _platform_menusu(self) -> tuple[str, list]:
        sat = []
        for p, ad in (("twitch", "Twitch"), ("kick", "Kick"), ("youtube", "YouTube")):
            ac = self._platform_acik_mi(p)
            sat.append({"text": f"{'✅' if ac else '❌'} {ad}", "callback_data": f"pl:{p}"})
        oto = self._oto_acik_mi()
        klavye = [sat, [{"text": ("🤖 Otomatik bul: AÇIK" if oto else "⭐ Sadece benim seçtiklerim"),
                         "callback_data": "pl:oto"}]]
        metin = ("📡 Hangi platformlara bakayım?\n"
                 "Dokununca açılır/kapanır.\n\n"
                 f"🤖 Otomatik bul AÇIK: en çok izlenen {OYUN.kisa} yayınlarını kendim seçerim (+ senin eklediklerin).\n"
                 "⭐ Sadece benim seçtiklerim: sadece /yayinlar'dan ⭐ yaptıklarını izlerim.")
        return metin, klavye

    def _yayin_menusu(self) -> tuple[str, list]:
        izlenen = set(self.izleyiciler)
        yasak = self._yasaklar()
        klavye = []
        for k, izl in self.son_bulunan[:30]:
            ekli = (k.tutamac or k.ad) in self._liste(k.platform)
            yasakli = k.ad.lower() in yasak or k.gorunen.lower() in yasak
            ikon = "⛔" if yasakli else "⭐" if ekli else "👁" if k.anahtar in izlenen else "➕"
            kisa = {"twitch": "TW", "kick": "KICK", "youtube": "YT"}[k.platform]
            izl_s = f"{izl / 1000:.1f}K" if izl >= 1000 else str(izl)
            ad = k.ad if k.platform != "youtube" else (k.tutamac or "@" + k.gorunen.replace(" ", ""))
            klavye.append([
                {"text": f"{ikon} {k.gorunen[:18]} · {kisa} · {izl_s}", "callback_data": f"ek:{k.platform}:{ad}"[:64]},
                {"text": "⛔", "callback_data": f"ya:{k.platform}:{ad}"[:64]},
            ])
        klavye.append([{"text": "🔄 Yenile", "callback_data": "yy:"}, {"text": "📡 Platformlar", "callback_data": "pm:"}])
        ne_zaman = int((time.time() - self.son_tarama) / 60) if self.son_tarama else None
        metin = (f"🎮 Şu an açık {OYUN.kisa} yayınları ({len(self.son_bulunan)})"
                 + (f" — {ne_zaman} dk önce" if ne_zaman else "") + "\n\n"
                 "Dokun: ⭐ izle listeme ekle (tekrar dokun: çıkar) · ⛔ asla klipleme\n"
                 "👁 = şu an izleniyor · ➕ = izlenmiyor")
        if not self.son_bulunan:
            metin += "\n\n(Hiç yayın bulunamadı — platformlar kapalı olabilir ya da internet sorunu var.)"
        return metin, klavye

    def _hesap_menusu(self) -> tuple[str, list]:
        acik = {h["ad"] for h in self._hesaplar()}
        sat = [{"text": f"{'✅' if h['ad'] in acik else '❌'} {h['ad']} ({h['dil']})", "callback_data": f"hs:{h['ad']}"}
               for h in self._hesaplar(hepsi=True)]
        imzalar = "\n".join(f"{h['ad']}: {h['imza'] or '(yok)'}" for h in self._hesaplar(hepsi=True))
        return (f"👤 Hesaplar — her açık hesap için ayrı dilde video + açıklama üretilir.\n\n"
                f"Videonun altındaki isim:\n{imzalar}\n\nDeğiştirmek için: /isim @kullaniciadi  "
                f"(sadece birine: /isim tr @x)"), [sat]

    async def _yayin_menusu_gonder(self) -> None:
        if time.time() - self.son_tarama > 120:
            try:
                await self._tara(40)
            except Exception as e:  # noqa: BLE001
                log.warning("tarama hatası: %r", e)
        await self.bot.butonlu(*self._yayin_menusu())

    async def _buton(self, data: str) -> tuple:
        tur, _, kalan = data.partition(":")
        if tur == "pl":
            d = self._durum_oku()
            if kalan == "oto":
                d["oto"] = not self._oto_acik_mi()
                cevap = "Otomatik bulma " + ("açıldı 🤖" if d["oto"] else "kapandı — sadece senin seçtiklerin ⭐")
            else:
                d.setdefault("platform", {})[kalan] = not self._platform_acik_mi(kalan)
                cevap = f"{kalan} " + ("açıldı ✅" if d["platform"][kalan] else "kapandı ❌")
                if not d["platform"][kalan]:
                    for a, iz in list(self.izleyiciler.items()):
                        if iz.kanal.platform == kalan:
                            await self._birak(a)
            self._durum_yaz(d)
            self._uyandir.set()
            return (cevap, *self._platform_menusu())
        if tur in ("pd", "pa"):
            hid = kalan
            hesap = hid.rsplit("_", 1)[-1]
            if tur == "pd":
                await asyncio.to_thread(self.plan.paylasildi, hesap, hid)
                return ("Süper, paylaşıldı olarak işaretlendi ✅", None,
                        [[{"text": "✅ Paylaşıldı", "callback_data": "x:"}]])
            self.plan.isaretle(hid, "atlandi")
            return ("Atlandı ⏭ (stokta kalır)", None, [[{"text": "⏭ Atlandı", "callback_data": "x:"}]])
        if tur == "hs":
            d = self._durum_oku()
            kapali = set(d.get("hesap_kapali") or [])
            kapali ^= {kalan}
            if len(kapali) >= len(self._hesaplar(hepsi=True)):
                return ("En az bir hesap açık kalmalı", None, None)
            d["hesap_kapali"] = sorted(kapali)
            self._durum_yaz(d)
            return (f"{kalan} " + ("kapandı" if kalan in kapali else "açıldı"), *self._hesap_menusu())
        if tur == "pm":
            return ("", *self._platform_menusu())
        if tur == "yy":
            await self._tara(40)
            return ("Yenilendi 🔄", *self._yayin_menusu())
        if tur in ("ek", "ya"):
            platform, _, ad = kalan.partition(":")
            if tur == "ya":
                cevap = await self._komut(f"/yasakla {ad}")
            elif ad in self._liste(platform):
                cevap = await self._komut(f"/cikar {platform} {ad}")
            else:   # listedeki yayın zaten açık: tekrar kontrol etmeye gerek yok (hızlı)
                cevap = await self._ekle(f"{platform} {ad}", canli_biliniyor=True)
            return (cevap.split("\n")[0][:190], *self._yayin_menusu())
        return ("", None, None)

    async def _ekle(self, metin: str, canli_biliniyor: bool = False) -> str:
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
        if canli_biliniyor:
            canli = True
        elif platform == "kick":
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
        dolu = len(self.izleyiciler) >= self._sinir()
        ek = "\n⚠️ İzleme sınırı dolu; yer açılınca girer (/sinir ile artırabilirsin)." if dolu and canli else ""
        return f"✅ {ad} ({platform}) eklendi — {durum}.{ek}"

    # ---------- günlük paylaşım planı ----------
    async def planci(self) -> None:
        """Her dakika: bugünün planı var mı, saati gelen paylaşım var mı, akşam stok raporu, günlük trend."""
        son_rapor, son_trend, son_meme = "", 0.0, self._durum_oku().get("son_meme", "")
        son_surum_kontrol = 0.0
        while True:
            try:
                simdi = zaman.now()
                hesaplar = [h["ad"] for h in self._hesaplar()]
                adet = self._gunluk()
                self.plan.plan_yap(simdi.date(), hesaplar, adet, simdi)
                for hesap, it in self.plan.zamani_gelenler(simdi):
                    if await self._paylasim_hatirlat(hesap, it):
                        self.plan.isaretle(it["hid"], "gonderildi", simdi.date().isoformat())
                if simdi.hour >= 10 and son_meme != simdi.date().isoformat():
                    son_meme = simdi.date().isoformat()
                    d = self._durum_oku()
                    d["son_meme"] = son_meme
                    self._durum_yaz(d)
                    n = await self.meme_uret()
                    if n:
                        log.info("günün meme'leri hazır: %d", n)
                    for eski in (self.klasor / "ham").glob("*.mp4"):
                        if eski.stat().st_mtime < time.time() - 3 * 86400:
                            eski.unlink(missing_ok=True)
                if time.time() - son_surum_kontrol > 6 * 3600:
                    son_surum_kontrol = time.time()
                    from . import guncelle as g
                    var, yerel, uzak = await asyncio.to_thread(g.yeni_var_mi)
                    if var and self._durum_oku().get("bildirilen_surum") != uzak:
                        d = self._durum_oku()
                        d["bildirilen_surum"] = uzak
                        self._durum_yaz(d)
                        await self.bot.mesaj(f"🆕 Yeni sürüm var ({yerel} → {uzak}). Kurmak için /guncelle yaz.")
                rapor_saat = str(self.cfg.get("stok_rapor_saati", "21:30"))
                if simdi.strftime("%H:%M") >= rapor_saat and son_rapor != simdi.date().isoformat():
                    son_rapor = simdi.date().isoformat()
                    await self.bot.mesaj(self._stok_metni(yarin=True))
                if self.yazar.client and time.time() - son_trend > 24 * 3600:
                    son_trend = time.time()
                    try:
                        self.yazar.trend = await asyncio.to_thread(trend_arastir, self.yazar)
                        if self.yazar.trend:
                            (self.klasor / "trend.txt").write_text(self.yazar.trend, encoding="utf-8")
                            log.info("günlük trend araştırması güncellendi")
                    except Exception as e:  # noqa: BLE001
                        log.warning("trend araştırması olmadı: %r", e)
            except Exception:  # noqa: BLE001
                log.exception("plan hatası")
            await asyncio.sleep(60)

    async def meme_uret(self, adet: int | None = None) -> int:
        """Her açık hesap için meme videosu yap ve onaya yolla. Kaç tane yapıldığını döndürür."""
        adet = int(self.cfg.get("gunluk_meme", 2)) if adet is None else adet
        hamlar = sorted((self.klasor / "ham").glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
        if not hamlar or adet <= 0:
            return 0
        d = self._durum_oku()
        kullanilan = set(d.get("kullanilan_meme") or [])
        yapilan = 0
        for h in self._hesaplar():
            metinler = await asyncio.to_thread(meme.meme_metinleri, self.yazar, h["dil"], adet, kullanilan)
            for i, (yazi, aciklama) in enumerate(metinler):
                hid = f"{zaman.now().strftime('%Y%m%d_%H%M%S')}_meme{i}_{h['ad']}"
                klasor = self.klasor / "bekleyen" / hid
                klasor.mkdir(parents=True, exist_ok=True)
                mp4 = klasor / f"{hid}.mp4"
                try:
                    await asyncio.to_thread(meme.meme_video, random.choice(hamlar), yazi, mp4, h["imza"])
                except Exception as e:  # noqa: BLE001
                    log.warning("meme yapılamadı: %r", e)
                    shutil.rmtree(klasor, ignore_errors=True)
                    continue
                tek = yazi.replace("\n", " / ")
                tags = f"{OYUN.etiket} #meme"
                pm = {"instagram": f"{aciklama} {tags}".strip(), "tiktok": f"{aciklama} {tags}".strip(),
                      "youtube_baslik": f"{tek[:85]} #shorts", "youtube_aciklama": f"{tek}\n{tags} #shorts"}
                (klasor / "aciklama.json").write_text(json.dumps(pm, ensure_ascii=False, indent=1), encoding="utf-8")
                (klasor / "aciklama.txt").write_text(pm["instagram"], encoding="utf-8")
                (klasor / "bilgi.json").write_text(json.dumps({
                    "yayinci": "meme", "platform": "meme", "hesap": h["ad"], "dil": h["dil"], "puan": 6.0,
                    "neden": "günlük meme", "meme": yazi}, ensure_ascii=False, indent=1), encoding="utf-8")
                kullanilan.add(yazi)
                yapilan += 1
                await self._gonder(klasor)
        d = self._durum_oku()
        d["kullanilan_meme"] = sorted(kullanilan)[-200:]
        self._durum_yaz(d)
        return yapilan

    async def _paylasim_hatirlat(self, hesap: str, it: dict) -> bool:
        k = self.klasor / "hazir" / hesap / it["hid"]
        mp4 = next(iter(k.glob("*.mp4")), None) if k.exists() else None
        if not mp4:
            self.plan.isaretle(it["hid"], "kayip")
            return False
        try:
            pm = json.loads((k / "aciklama.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pm = {}
        try:
            await self.bot.video_gonder(mp4, f"⏰ PAYLAŞIM ZAMANI — {hesap} hesabı ({it['saat']})\n"
                                             f"Videoyu kaydet → Instagram, TikTok, YouTube'a yükle.", it["hid"],
                                        butonlar=[[{"text": "✅ Paylaştım", "callback_data": f"pd:{it['hid']}"[:64]},
                                                   {"text": "⏭ Atla", "callback_data": f"pa:{it['hid']}"[:64]}]])
            parca = [f"<b>⏰ {escape(hesap)} — {it['saat']}</b>  (metne dokun → kopyalanır)"]
            for baslik, anahtar in (("📸 Instagram", "instagram"), ("🎵 TikTok", "tiktok"),
                                    ("▶️ YouTube başlık", "youtube_baslik"), ("▶️ YouTube açıklama", "youtube_aciklama")):
                if pm.get(anahtar):
                    parca.append(f"{baslik}:\n<code>{escape(pm[anahtar])}</code>")
            await self.bot.html("\n\n".join(parca))
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("paylaşım hatırlatması gönderilemedi: %r", e)
            return False

    def _stok_metni(self, yarin: bool = False) -> str:
        hedef_n = self._hedef_stok()
        adet = self._gunluk()
        satir = ["📦 Stok durumu" + (" (yarın için)" if yarin else "")]
        for h in self._hesaplar():
            n = len(self.plan.stok(h["ad"]))
            ikon = "✅" if n >= hedef_n else "⚠️" if n >= adet else "❌"
            satir.append(f"{ikon} {h['ad']}: {n} video hazır (hedef {hedef_n}, günde {adet} paylaşım)")
        if any(len(self.plan.stok(h["ad"])) < adet for h in self._hesaplar()):
            satir.append("\nStok az: gelen kliplere ✅ bas, ya da /yayinlar'dan daha çok yayıncı seç.")
        return "\n".join(satir)

    def _plan_metni(self) -> str:
        g = self.plan.gun_plani(tarih.today())
        if not g:
            return "Bugün için plan yok (stok boş olabilir). /stok"
        ikon = {"bekliyor": "🕒", "gonderildi": "📨", "paylasildi": "✅", "atlandi": "⏭", "kayip": "❓"}
        satir = ["📅 Bugünün paylaşım planı"]
        for hesap, lst in g.items():
            satir.append(f"\n{hesap}:")
            for it in lst:
                satir.append(f"{ikon.get(it['durum'], '•')} {it['saat']} — {planmod.yayinci_adi(it['hid'])}")
        satir.append("\n🕒 bekliyor · 📨 sana gönderildi · ✅ paylaştın")
        return "\n".join(satir)

    async def _hazirlik(self) -> None:
        """Arka planda: yüz modeli + altyazı modeli hazırla (ilk klip beklemesin). İnternet yoksa tekrar dener."""
        await asyncio.to_thread(yuz.model_indir)
        if not self.yaziya:
            return

        async def gec_kaldi_mi():
            await asyncio.sleep(600)
            if not self.yaziya.hazir:
                try:
                    await self.bot.mesaj("⏳ Altyazı aracı 10 dakikadır hazırlanıyor (model iniyor olabilir). "
                                         "Bu sırada klipler altyazısız gelir.\nDurum: " + self.yaziya.durum)
                except Exception:  # noqa: BLE001
                    pass
        bekci = asyncio.create_task(gec_kaldi_mi())
        uyardi = False
        while not await asyncio.to_thread(self.yaziya.onyukle):
            if not uyardi:
                uyardi = True
                ek = ("\nAltyazı paketi kurulu değil: programı kapatıp GUNCELLE.bat'a çift tıkla."
                      if "faster_whisper" in self.yaziya.durum else "")
                try:
                    await self.bot.mesaj("⚠️ Konuşma altyazısı hazırlanamadı, videolar altyazısız gelecek.\n"
                                         f"Neden: {self.yaziya.durum}" + ek)
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(300)
        bekci.cancel()
        try:
            await self.bot.mesaj(f"✅ Altyazı aracı hazır ({self.yaziya.durum}). Klipler artık altyazılı gelecek.")
        except Exception:  # noqa: BLE001
            pass

    # ---------- çalıştır ----------
    async def calistir(self) -> None:
        if not self.bot.token:
            raise SystemExit("config.yaml içinde telegram.bot_token boş! README'deki adımlara bak.")
        (self.klasor / "_is").mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(yetim_kayitlari_kapat, self._tampon_kok())
        n_isci = max(1, int(self.cfg.get("ayni_anda_kurgu", 2)))
        gorevler = [asyncio.create_task(self.bot.dinle()), asyncio.create_task(self.yonetici())]
        gorevler += [asyncio.create_task(self.isci()) for _ in range(n_isci)]
        gorevler.append(asyncio.create_task(self.gonderici()))
        gorevler.append(asyncio.create_task(self._hazirlik()))
        gorevler.append(asyncio.create_task(self.planci()))
        gorevler.append(asyncio.create_task(self.hiz_ayari()))
        gorevler.append(asyncio.create_task(self.saglik_ayari()))
        try:
            await self.bot.komut_menusu()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.bot.mesaj(f"▶ {OYUN.kisa} Klipçi açıldı (sürüm {SURUM}). Yayınlar aranıyor... (/durum)")
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram'a ulaşılamadı: %s", e)
        try:
            await asyncio.gather(*gorevler)
        finally:
            for a in list(self.izleyiciler):
                await self._birak(a)
