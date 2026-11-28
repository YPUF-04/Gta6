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
from .kurgu import ass_yaz, chat_sec, dikey_video, guvenli_kopya, ses_cikar, tweet_video, video_saglam_mi
from .spike import Spike, SpikeDetector, mesaj_puani, yazi_dili
from .ceviri import cevir as ceviri_yap
from .oyunsesi import bagirma_mi, oyun_aksiyonu, parca_sesi, ses_zirvesi
from .oyunsesi import hareketsiz_oran, oyun_altyazi_anlari, oyun_konusmasi_mi, yuz_tepkisi
from .oyunsesi import karanlik_anlar, karanliktan_kirp
from .telegram import Bot
from .yazar import Yazar, paylasim_metni, platform_metinleri, trend_arastir

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
    ses_gecmis: deque = field(default_factory=lambda: deque(maxlen=600))   # son ~5 dk ses şiddeti (yarım sn)
    son_ses_parca: str = ""


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
        self.bot.on_belge = self._belge
        self._arka: set = set()
        # İkinci Telegram botu: "paylaşım kanalı" (onayladıkların, paylaşılanlar, TikTok hatırlatması, 10:00 özeti)
        self.bot2: Bot | None = None
        from .performans import Performans
        self.performans = Performans(self.klasor / "istatistik.json")
        from .trend import Trend
        self.trend = Trend(self.kok / "trend.json")
        self._bot2_kur(tg.get("paylasim_bot_token") or durum.get("bot2_token", ""))
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
        self._son_istatistik = 0.0
        self._son_tekrar = 0.0
        self.basladi = time.time()
        self.son_bulunan: list[tuple[kesif.Kanal, int]] = []
        self.son_tarama = 0.0
        self.ogrenci = puan.Ogrenci(self.klasor / "puan_gecmisi.jsonl")
        self.plan = planmod.Planlayici(self.klasor)
        self.plan.carpan = self.performans.yayinci_carpani
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
        self._kabul_gecmisi: list[float] = []   # tüm kontrolleri geçip video olan klipler (saatlik kota)
        self._kesim_gecmisi: list[float] = []   # kesilen (incelemeye giren) klipler
        # dilini atladığımız (ör. Arapça) yayınlar — kalıcı
        self._yabanci: set[str] = set(self._durum_oku().get("atlanan_kanallar") or [])
        self._kapali: dict[str, float] = {}   # yakın zamanda kapalı bulunan kanallar

    # ---------- durum ----------
    def _durum_oku(self) -> dict:
        try:
            return json.loads(self.durum_yolu.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _bot2_kur(self, token: str) -> None:
        if not token:
            return

        def kaydet(cid: str) -> None:
            d = self._durum_oku()
            d["bot2_chat"] = cid
            self._durum_yaz(d)
        # sadece senin konuşmana cevap versin: ana botla aynı kişi (/start yazan ilk kişi)
        self.bot2 = Bot(token, self._durum_oku().get("bot2_chat", ""), kaydet)
        self.bot2.on_komut = self._komut2
        self.bot2.on_buton = self._buton

    def _paylas_botu(self) -> Bot:
        """Paylaşımla ilgili mesajlar ikinci bota (kuruluysa), yoksa ana bota."""
        return self.bot2 if self.bot2 and self.bot2.chat_id else self.bot

    async def _komut2(self, metin: str) -> str:
        k = metin.split()[0].lower().split("@")[0] if metin.split() else ""
        if k in ("/bugun", "/bugün", "/paylasilanlar", "/paylaşılanlar"):
            return self._paylasim_ozeti(zaman.now().date(), "Bugün")
        if k in ("/istatistik", "/performans", "/izlenme"):
            await asyncio.to_thread(self.performans.guncelle, self._istatistik_cek)
            return self.performans.rapor()
        if k in ("/dun", "/dün"):
            return self._paylasim_ozeti(zaman.now().date() - timedelta(days=1), "Dün")
        if k in ("/plan", "/stok", "/paylasim", "/paylaşım"):
            return await self._komut(metin)
        return ("📤 PAYLAŞIM KANALI\nBuraya paylaşılan videolar, TikTok hatırlatmaları ve her sabah 10:00'da özet gelir.\n"
                "/bugun — bugün paylaşılanlar · /dun — dün · /istatistik — izlenmeler ve öneri\n"
                "/plan — paylaşım saatleri · /stok")

    def _istatistik_cek(self, plat: str, kimlik: str, hesap: str) -> dict | None:
        from . import paylas
        h = next((x for x in self._hesaplar(hepsi=True) if x["ad"] == hesap), {})
        if plat == "instagram" and h.get("instagram_token"):
            return paylas.ig_istatistik(paylas.Instagram(h["instagram_token"], self.kok / "instagram" / f"{hesap}.json"),
                                        kimlik)
        if plat == "youtube":
            yt = paylas.YouTube(self._yt_istemci(hesap), self.kok / "youtube" / f"{hesap}.json")
            return yt.istatistik(kimlik) if yt.bagli_mi() else None
        return None

    def _paylasim_ozeti(self, gun, baslik: str) -> str:
        g = self.plan.gun_plani(gun)
        satir = [f"📊 {baslik} ({gun.strftime('%d.%m')}) paylaşılanlar"]
        n = 0
        for hesap, lst in sorted(g.items()):
            for it in lst:
                if it.get("durum") not in ("gonderildi", "paylasildi"):
                    continue
                n += 1
                pf = it.get("sonuclar") or (it.get("platformlar") if isinstance(it.get("platformlar"), dict) else {}) or {}

                def ik(p: str, e: str) -> str:
                    v = str(pf.get(p, ""))
                    return f"{e}{'✅' if v and not v.startswith('HATA') else '⚠️' if v.startswith('HATA') else '⏳'}"
                ekler = "".join(f" {ik(p, e)}" for p, e in (("facebook", "📘"), ("threads", "🧵")) if p in pf)
                satir.append(f"• {it['saat']} {planmod.yayinci_adi(it['hid'])} [{hesap}]  "
                             f"{ik('instagram', '📸')} {ik('youtube', '▶️')} {ik('tiktok', '🎵')}{ekler}")
        if not n:
            satir.append("— henüz yok")
        satir.append("\n📸 Instagram · ▶️ YouTube · 🎵 TikTok · 📘 Facebook · 🧵 Threads\n✅ paylaşıldı · ⏳ bekliyor · ⚠️ olmadı")
        return "\n".join(satir)

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
                tanim[ad] = {"ad": ad, "dil": h.get("dil", "tr" if ad == "TR" else "en"), "imza": h.get("imza", ""),
                             # Telegram'dan /bagla ile girilen anahtar önce gelir
                             "instagram_token": str((self._durum_oku().get("ig_token") or {}).get(ad, ""))
                             or str(h.get("instagram_token") or "").strip(),
                             "youtube": bool(h.get("youtube", True)),
                             "facebook_token": str((self._durum_oku().get("fb_token") or {}).get(ad, "")),
                             "threads_token": str((self._durum_oku().get("th_token") or {}).get(ad, ""))}
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
        """Türkçe yayın -> Türkçe hesap (Türkçe altyazı). Diğer HER yayın -> İngilizce hesap (İngilizce altyazı;
        yayıncı İngilizce konuşmuyorsa konuşması İngilizceye çevrilir)."""
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
        return [k for k in (kesif.Kanal(p, a) for p in ("twitch", "kick") if self._platform_acik_mi(p)
                            for a in self._liste(p)) if k.anahtar not in self._yabanci]

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
        # YouTube Shorts'larda klipleri patlayan yayıncılar öne (izleyici sayısı x 1.5'e kadar)
        out.sort(key=lambda x: -x[1] * (1 + 0.5 * min(1.0, self.trend.yayinci_puani(x[0].ad, x[0].gorunen))))
        self.son_bulunan, self.son_tarama = out, time.time()
        return out

    def _bildirim_acik(self) -> bool:
        d = self._durum_oku()
        return bool(d.get("bildirim", self.cfg.get("bildirimler", False)))

    async def _bildir(self, metin: str) -> None:
        """Kendiliğinden giden bilgi mesajları (açıldı, klip hazırlanıyor, stok raporu...).
        Varsayılan KAPALI: Telegram'a sadece videolar ve senin komutlarının cevapları gelir. /bildirim ac ile açılır."""
        if self._bildirim_acik():
            await self.bot.mesaj(metin)
        else:
            log.info("(Telegram'a yollanmadı, bildirimler kapalı) %s", metin.splitlines()[0][:120])

    def _yabanci_cevir(self) -> bool:
        """Başka dilde konuşan yayıncılar: altyazıyı İngilizceye çevirip kullan (True) ya da hiç alma (False)."""
        return bool(self.cfg.get("yabanci_dil_cevir", True))

    def _atlanan_diller(self) -> set[str]:
        """Hiç izlenmeyecek diller (varsayılan: Arapça)."""
        return {str(d).lower() for d in (self.cfg.get("atlanan_diller") or ["ar"])}

    def _dil_atla(self, dil: str) -> bool:
        dil = (dil or "").lower()[:2]
        if not dil:
            return False
        return dil in self._atlanan_diller() or (not self._yabanci_cevir() and dil not in self._izinli_diller())

    def _yabanciya_ekle(self, anahtar: str) -> None:
        """Bir daha izleme (program kapanıp açılsa da)."""
        self._yabanci.add(anahtar)
        d = self._durum_oku()
        d["atlanan_kanallar"] = sorted(set(d.get("atlanan_kanallar") or []) | {anahtar})[-500:]
        self._durum_yaz(d)

    def _izinli_diller(self) -> set[str]:
        return {str(d).lower() for d in (self.cfg.get("izin_verilen_diller") or [h["dil"] for h in self._hesaplar()])}

    async def _adaylar_oto(self, adet: int) -> list[tuple[kesif.Kanal, int]]:
        bulunan = await self._tara(adet)
        if not self._oto_acik_mi():
            return []
        # sadece hesap açtığın dillerdeki yayınlar (dili bilinmeyenler de alınır)
        diller = self._izinli_diller()
        bulunan = [x for x in bulunan if (not x[0].dil or x[0].dil in diller or not self._dil_atla(x[0].dil))
                   and x[0].dil not in self._atlanan_diller() and x[0].anahtar not in self._yabanci]
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

    def _aralik(self) -> float:
        """Kaç saatte bir paylaşım (varsayılan 3). 0 = eski usul günlük adet (/gunluk)."""
        try:
            return float(self._durum_oku().get("aralik", self.cfg.get("paylasim_araligi_saat", 5)))
        except (TypeError, ValueError):
            return 3.0

    # Sabit paylaşım saatleri (Türkiye saati). Araştırma: Reels sabah 08-10, öğle 12-14, akşam 19-21 en iyi;
    # oyun içeriği akşam 18-23 güçlü. EN hesabının izleyicisi ABD: ABD öğle-akşamı = TR 19:00-05:30.
    # Her saatin gideceği platformlar: Instagram günde 3 (en iyi saatler), YouTube 2, Facebook 4, Threads 3,
    # TikTok her saatte (elle). ig=Instagram fb=Facebook yt=YouTube th=Threads
    SABIT_SAATLER = {
        "TR": [("09:00", "fb"), ("11:00", "th"), ("12:30", "ig fb"), ("14:00", "th"), ("16:00", "fb"),
               ("18:00", "th"), ("19:30", "ig yt"), ("20:30", "fb"), ("21:30", "ig"), ("23:00", "yt")],
        "EN": [("15:00", "fb"), ("17:00", "th"), ("19:00", "ig fb"), ("20:30", "yt"), ("22:00", "th"),
               ("23:30", "ig fb"), ("01:00", "th"), ("02:30", "yt"), ("04:00", "ig fb"), ("05:30", "")],
    }
    KISA = {"ig": "instagram", "fb": "facebook", "yt": "youtube", "th": "threads"}

    def _sabit_saatler(self) -> dict:
        """{hesap: [(HH:MM, [platformlar]), ...]} — /saatler ile görülür, config 'paylasim_saatleri' ile değişir."""
        if not self.cfg.get("sabit_saatler", True):
            return {}
        kaynak = self.cfg.get("paylasim_saatleri") or self.SABIT_SAATLER
        out = {}
        for h, lst in kaynak.items():
            out[str(h).upper()] = [(str(x[0]) if isinstance(x, (list, tuple)) else str(x.get("saat")),
                                    [self.KISA.get(k, k) for k in (x[1] if isinstance(x, (list, tuple))
                                                                   else x.get("platformlar", "")).split()])
                                   for x in lst]
        return out

    def _tam_otomatik(self) -> bool:
        """Saat gelince senin onayını beklemeden en iyi klibi kendisi paylaşsın mı? (varsayılan: evet)"""
        return bool(self._durum_oku().get("tam_otomatik", self.cfg.get("tam_otomatik", True)))

    def _en_iyi_aday(self, hesap: str, neden_dondur: bool = False):
        """Paylaşım saatinde bu hesap için "en güzel olduğuna inandığı" klip. Sadece en yüksek puana bakmaz:
        - kalite puanı (temel),
        - izlenmelerden öğrendiği: bu tarz klipler bu hesapta iyi gidiyor mu (öğrenci modeli),
        - yayıncının bu hesaptaki izlenme geçmişi, senin 😍 / ✅ / 👍 bastıkların,
        - çeşitlilik: aynı yayıncı art arda / gün içinde tekrar tekrar gitmesin (takipçi sıkılmasın),
        - tazelik: yeni anlar eskilerden önce, yayıncının konuştuğu (kancalı) klipler biraz önde.
        En az 'oto_en_dusuk_puan' (varsayılan 7) olmalı."""
        en_az = float(self.cfg.get("oto_en_dusuk_puan", 7))
        adaylar: list[tuple[float, str, str]] = []
        # bugün bu hesapta giden yayıncılar (çeşitlilik için)
        bugun = [it for it in (self.plan.gun_plani(datetime.now().date()).get(hesap) or [])
                 if it.get("hid") and it.get("durum") in ("gonderildi", "paylasildi")]
        bugun.sort(key=lambda it: it.get("saat", ""))
        giden = [planmod.yayinci_adi(it["hid"]) for it in bugun]
        yerler = [(k, True) for k in (self.klasor / "hazir" / hesap).glob("*")]
        yerler += [(k, False) for k in (self.klasor / "bekleyen").glob(f"*_{hesap}")]
        for k, onayli in yerler:
            if not k.is_dir() or not list(k.glob("*.mp4")) or self.plan.planli_mi(k.name):
                continue
            try:
                b = json.loads((k / "bilgi.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if time.time() - k.stat().st_mtime > 3 * 86400:   # 3 günden eski anlar bayatlar
                continue
            p = float(b.get("puan", 0))
            if p < en_az:
                continue
            # eski sürümlerin yaptığı klipler (mor altyazı, yarım/kısa, ara sahne...) artık paylaşılmaz;
            # 15 sn'den kısa klip de yarım gibi durur
            if not b.get("surum") or float(b.get("sure", 99)) < 15:
                continue
            kayit = self.ogrenci.kayitlar.get(k.name) or {}
            karar = kayit.get("karar")
            if karar == "sil":
                continue
            yay = planmod.yayinci_adi(k.name)
            notlar = [f"puan {p:.1f}"]
            ol = self.ogrenci.olasilik(b.get("ozellikler") or kayit.get("oz") or {})
            if ol is not None:                                 # izlenmelerden öğrendiği tarz
                ek = round(3.0 * (ol - 0.5), 1)
                p += ek
                if abs(ek) >= 0.3:
                    notlar.append(f"izlenmelerden öğrendiğim {ek:+.1f}")
            if onayli or karar == "onay":
                p += 0.5
            c = self.performans.yayinci_carpani(yay)
            p *= c
            if abs(c - 1) >= 0.05:
                notlar.append(f"{yay} bu hesapta x{c:.2f}")
            fav = (self._durum_oku().get("favori") or {}).get(yay, 0)
            p *= min(1.2, 1 + 0.05 * fav)                     # 😍 bastığın yayıncılar öne
            tp = self.trend.yayinci_puani(yay, str(b.get("yayinci") or ""))
            if tp > 0:                                        # Shorts'larda şu an patlayan yayıncı
                p += min(0.6, 0.3 * tp)
                notlar.append(f"trend yayıncı +{min(0.6, 0.3 * tp):.1f}")
            if kayit.get("bayildi"):
                p += 2.0                                      # 😍 bastığın klip ilk gider
                notlar.append("😍")
            # çeşitlilik: aynı yayıncı art arda gitmesin, gün içinde de çok tekrar etmesin
            if giden and giden[-1] == yay:
                p -= 1.5
                notlar.append("az önce de bu yayıncı gitti")
            elif giden.count(yay):
                p -= 0.6 * giden.count(yay)
                notlar.append(f"bugün {giden.count(yay)} kez gitti")
            # tazelik: günde ~0.4 puan eskir
            p -= 0.4 * (time.time() - k.stat().st_mtime) / 86400
            # kanca: yayıncı konuşuyorsa (altyazılı, ilk saniyeden ilgi çeker) biraz önde
            if b.get("transkript"):
                p += 0.3
            adaylar.append((p, k.name, ", ".join(notlar)))
        if not adaylar:
            return ("", "") if neden_dondur else ""
        en = max(adaylar)
        return (en[1], f"{en[0]:.1f} — " + en[2]) if neden_dondur else en[1]

    def _hazira_al(self, kid: str) -> None:
        """Onay beklemeden seçilen klibi paylaşılacaklar klasörüne taşı."""
        yer = self._klip_yeri(kid)
        if yer and yer[0] == "bekleyen":
            hedef = self.klasor / "hazir" / kid.rsplit("_", 1)[-1] / kid
            hedef.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(yer[1]), str(hedef))

    def _gunluk(self) -> int:
        """Her hesap için günde kaç paylaşım (Telegram /gunluk ile değişir)."""
        sabit = self._sabit_saatler()
        if sabit:
            return max((len(v) for v in sabit.values()), default=10)
        if self._aralik():
            return len(planmod.aralikli_saatler(self._aralik(), tarih(2000, 1, 1)))
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

    async def _trend_guncelle(self) -> bool:
        """Bağlı bir YouTube hesabının anahtarıyla en çok izlenen GTA 6 Shorts'larını çek."""
        from . import paylas
        for h in self._hesaplar(hepsi=True):
            yt = paylas.YouTube(self._yt_istemci(h["ad"]), self.kok / "youtube" / f"{h['ad']}.json")
            if not yt.bagli_mi():
                continue
            try:
                n = await asyncio.to_thread(lambda: self.trend.guncelle(yt._erisim()))
                log.info("📈 YouTube trendleri güncellendi: %d popüler GTA 6 Shorts incelendi", n)
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("YouTube trendleri alınamadı (%s): %r", h["ad"], e)
        return False

    def _yorum_istekleri(self) -> dict:
        """Son 7 günde YouTube'a yüklediğimiz Shorts'ların yorumlarında hangi yayıncılar isteniyor?"""
        from . import paylas
        yorumlar: list[str] = []
        kayit = self.performans._oku()
        for hid, r in kayit.items():
            vid = (r.get("kimlik") or {}).get("youtube")
            if not vid or time.time() - r.get("t", 0) > 7 * 86400:
                continue
            yt = paylas.YouTube(self._yt_istemci(r.get("hesap", "")), self.kok / "youtube" / f"{r.get('hesap', '')}.json")
            if not yt.bagli_mi():
                continue
            try:
                yorumlar += yt.yorumlar(str(vid))
            except Exception as e:  # noqa: BLE001
                log.debug("yorumlar alınamadı (%s): %r", vid, e)
        if not yorumlar:
            return {}
        adaylar = [k.gorunen or k.ad for k, _ in (self.son_bulunan or [])]
        adaylar += [k.ad for k, _ in (self.son_bulunan or [])]
        adaylar += [str(r.get("yayinci") or "") for r in kayit.values()]
        say = self.trend.yorumlardan_istek(yorumlar, adaylar)
        if say:
            log.info("💬 yorumlarda istenen yayıncılar: %s", say)
        return say

    async def trend_dongu(self) -> None:
        """12 saatte bir YouTube'daki popüler GTA 6 Shorts'larından öğren (hangi yayıncı/tarz tutuyor)."""
        await asyncio.sleep(90)
        while True:
            try:
                if self.trend.eski_mi(12):
                    await self._trend_guncelle()
                    await asyncio.to_thread(self._yorum_istekleri)
            except Exception:  # noqa: BLE001
                log.exception("trend hatası")
            await asyncio.sleep(1800)

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
                kayipli = 0
                for iz in olgun:
                    d = await asyncio.to_thread(iz.kayit.durum)
                    # son 10 dk'da klip keserken kare kaybı görüldüyse o kayıt "akıyor" sayılmaz
                    zk, oran_k = getattr(iz.kayit, "son_kayip", (0.0, 1.0))
                    if simdi - zk < 600 and oran_k < 0.85:
                        kayipli += 1
                        continue
                    if d["son_parca_sn"] is not None and d["son_parca_sn"] < 30 and d["parca"] >= 5:
                        saglikli += 1
                oran = saglikli / len(olgun)
                eski = self._sinir()
                if oran < 0.7:
                    self.etkin_sinir = max(3, min(eski, len(self.izleyiciler)) - 2)
                elif kayipli and self._sinir() > 3:   # kare kaybı var: büyütme, biraz küçült
                    self.etkin_sinir = max(3, min(eski, len(self.izleyiciler)) - 2)
                elif oran >= 0.9 and self.etkin_sinir and self.etkin_sinir < self._ust_sinir():
                    self.etkin_sinir += 2
                if self._sinir() != eski:
                    log.info("kayıtların %%%d'i akıyor → aynı anda izlenen yayın: %d → %d", int(oran * 100),
                             eski, self._sinir())
                    if self._sinir() < eski:
                        try:
                            await self._bildir(f"⚙️ Bilgisayar {eski} yayını aynı anda kaldıramıyor (kayıtların "
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
                if int(time.time()) % 60 == 0 and len(iz.chat_log) >= 40:
                    yd = yazi_dili([m for _, _, m in list(iz.chat_log)[-150:]])
                    if yd and self._dil_atla(yd):
                        log.info("%s aslında %s konuşulan bir yayın (chat'e göre), bırakılıyor", iz.kanal.anahtar, yd)
                        self._yabanciya_ekle(iz.kanal.anahtar)
                        # ayrı görev: _birak bu döngünün kendi görevini de iptal eder
                        asyncio.create_task(self._birak(iz.kanal.anahtar))
                        return
                iz.algila.kat = self.dinamik_kat
                s = iz.algila.kontrol(time.time())
                # chat'e bakmadan da: yayıncı aniden bağırdıysa/çığlık attıysa (en yeni bitmiş kayıt parçasına bak)
                if not s and self.cfg.get("ses_tetik", True) and int(time.time()) % 4 == 0:
                    s = await self._ses_patlamasi(iz)
                if s:
                    self._spike_gecmisi.append(time.time())
                    butce = self._saatlik_butce()
                    son_saat = [t for t in self._kabul_gecmisi if t > time.time() - 3600]
                    # kota sadece gerçekten video olan (tüm kontrolleri geçen) kliplerden düşer; ayrıca bilgisayar
                    # boğulmasın diye saatte en fazla butce*5 kesim denenir
                    kesim = [t for t in self._kesim_gecmisi if t > time.time() - 3600]
                    if (len(son_saat) >= butce or len(kesim) >= butce * 5) and s.kat < self.dinamik_kat * 1.8:
                        self.sayac["kotada"] += 1
                        log.debug("chat patladı ama bu saatin klip kotası dolu (%d), sadece çok güçlü anlar alınıyor: %s",
                                 butce, iz.kanal.anahtar)
                        continue
                    if True:
                        yd = yazi_dili([m for _, _, m in list(iz.chat_log)[-200:]])
                        if yd and self._dil_atla(yd):
                            log.info("%s chat'i %s, bırakılıyor", iz.kanal.anahtar, yd)
                            self._yabanciya_ekle(iz.kanal.anahtar)
                            asyncio.create_task(self._birak(iz.kanal.anahtar))
                            return
                    son = [m for t, _, m in list(iz.chat_log) if t >= time.time() - 12]
                    tepki_o = sum(1 for m in son if mesaj_puani(m)[0] > 1
                                  and mesaj_puani(m)[1] not in ("w", "gg", "?", "??", "???")) / max(1, len(son))
                    klip_n = sum(1 for m in son if mesaj_puani(m)[1] == "clip")
                    if s.neden == "tekrar" and (s.tekrar in ("w", "gg", "f", "1", "2", "l") or s.tekrar.startswith("!")):
                        self.sayac["zayif"] = self.sayac.get("zayif", 0) + 1
                        continue   # herkes "W" / bot komutu yazıyor: an değil
                    if s.neden == "chat" and tepki_o < 0.15 and klip_n < 2:
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

    async def _ses_patlamasi(self, iz: Izleyici) -> Spike | None:
        try:
            parcalar = iz.kayit.parcalar()
        except Exception:  # noqa: BLE001
            return None
        if len(parcalar) < 2:
            return None
        parca, zaman = parcalar[-2]   # sonuncusu hâlâ yazılıyor
        if str(parca) == iz.son_ses_parca:
            return None
        iz.son_ses_parca = str(parca)
        yeni = await asyncio.to_thread(parca_sesi, parca)
        bagirdi = bagirma_mi(list(iz.ses_gecmis), yeni)
        iz.ses_gecmis.extend(yeni)
        simdi = time.time()
        if not bagirdi or simdi - iz.algila._son_spike < iz.algila.bekleme:
            return None
        iz.algila._son_spike = simdi
        log.info("🔊 %s: yayıncı/oyun aniden çok yükseldi, an inceleniyor", iz.kanal.anahtar)
        # ses görüntüyle aynı saatte; chat saatine çevir ki gecikme hesabı doğru çalışsın
        g = self._gecikme(iz.kanal)
        return Spike(zaman=zaman - g, tetik=simdi - g, puan=0, taban=1, kelimeler=["ses"], neden="ses",
                     ornek_mesajlar=[m for _, _, m in list(iz.chat_log)[-25:]])

    def _saatlik_butce(self) -> int:
        # yayınlar günde ~12 saat yoğun: günlük hedefi saatlere böl
        return max(10, round(int(self.cfg.get("hedef_gunluk_klip", 60)) / 6))

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
            self._kesim_gecmisi = [t for t in self._kesim_gecmisi if t > simdi - 3600]
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

    def _hedef_puan(self) -> float:
        """Video olması için gereken en düşük kalite puanı (0-10). Varsayılan 7."""
        v = self._durum_oku().get("kalite", self.cfg.get("hedef_puan", 7))
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 7.0
        return v if 1 <= v <= 10 else 7.0   # eski /kalite 50 (yüzde) ayarı → 7

    def _secicilik(self) -> float:   # eski ad (durum ekranı için)
        return self._hedef_puan()

    @staticmethod
    def kalite_puani(is_: "Is", ses_tepki: float, yuz_t: float, oyun_ani: bool, duran: float,
                     konustu: bool, aksiyon: float = 0.0, segler: list | None = None) -> tuple[float, str]:
        """Ücretsiz kalite puanı 0-10 ve kısa açıklama. Net komik/şok anlar ~7-9 alır."""
        from .spike import mesaj_puani
        gulme = Uygulama._gulme_orani(is_)
        # "clip" diyen FARKLI kişi sayısı (bir kişinin 10 kez yazması 1 sayılır)
        klip = len({k for t, k, m in is_.chat if is_.an - 3 <= t <= is_.an + 12 and mesaj_puani(m)[1] == "clip"})
        p, neden = 0.0, []
        p += 4.5 * min(1.0, gulme / 0.55)
        if gulme >= 0.3:
            neden.append("izleyiciler gülmekten kırıldı" if gulme >= 0.6 else "izleyiciler güldü")
        p += 1.5 * min(1.0, klip / 4)
        if klip:
            neden.append("izleyiciler klip istedi")
        if is_.spike.neden == "tekrar":
            p += 1.5 * min(1.0, is_.spike.tekrar_oran / 0.6)
            neden.append("herkes aynı şeyi yazdı")
        p += 2.0 * min(1.0, max(0.0, ses_tepki - 3) / 6)
        if ses_tepki >= 8:
            neden.append("yayıncı bağırdı")
        p += 1.5 * min(1.0, max(0.0, yuz_t - 1) / 2)
        if yuz_t >= 2:
            neden.append("yayıncı coştu")
        if oyun_ani:
            p += 1.5
            neden.append("oyun içi an")
        if is_.spike.neden == "chat":
            p += 1.0 * min(1.0, max(0.0, is_.spike.kat - 2) / 8)
        if konustu:
            p += 0.5
        # yayıncının anlatımı: o an heyecanla, hızlı konuşuyor mu? gülüyor mu? (bağırmasa da eğlenceli anlar)
        yakin = [(b, e, t) for b, e, t in (segler or []) if e >= is_.an - 5 and b <= is_.an + 8]
        if yakin:
            kelime = sum(len(t.split()) for _, _, t in yakin)
            hiz = kelime / max(4.0, min(13.0, max(e for _, e, _ in yakin) - min(b for b, _, _ in yakin)))
            if hiz >= 1.8:
                p += 1.2 * min(1.0, (hiz - 1.8) / 1.2 + 0.4)
                neden.append("yayıncı heyecanla anlatıyor")
            metin = " ".join(t for _, _, t in yakin).lower()
            if any(g in metin for g in ("haha", "ahah", "hehe", "jaja", "kahkaha", "güldü", "gülüyor", "laugh",
                                        "(gül", "[gül")):
                p += 1.2
                neden.append("yayıncı güldü")
        # aksiyon öne çıksın: kaza, patlama, kovalamaca (görüntü birden sertleşiyor)
        p += 2.0 * min(1.0, max(0.0, aksiyon - 1.3) / 1.7)
        if aksiyon >= 2.0:
            neden.append("aksiyon")
        p -= 2.0 * duran
        # DÜZGÜN PUAN: yüksek puan için birden fazla BAĞIMSIZ işaret gerekir. Tek bir işaret (sadece chat,
        # sadece ses...) yanıltıcı olabilir: oyunun kendi sesi, chat spam'i, ara sahne vb.
        isaret = sum([gulme >= 0.3 or klip >= 2 or is_.spike.neden == "tekrar",   # izleyiciler
                      ses_tepki >= 6,                                             # yayıncı sesi
                      yuz_t >= 1.6,                                               # yayıncı yüzü
                      bool(yakin) and sum(len(t.split()) for _, _, t in yakin) >= 6,  # yayıncı anlatıyor
                      aksiyon >= 2.0])                                            # oyunda aksiyon
        if isaret <= 1:
            p = min(p, 7.2)
        elif isaret == 2:
            p = min(p, 8.6)
        # yayıncı klipte neredeyse hiç konuşmuyorsa izleyici bağ kuramaz
        if sum(max(0.0, e - b) for b, e, _ in (segler or [])) < 3:
            p -= 0.8
        return round(max(0.0, min(10.0, p)), 1), ", ".join(neden)

    @staticmethod
    def _akilli_aralik(is_: "Is", segler: list, giris_sn: float = 6.0) -> tuple[float, float]:
        """Klibin gerçekten izlenecek kısmı (klip içi saniyeler): (başlangıç, bitiş).
        Bitiş: chat'in gülme/şaşırma tepkisi söndükten ~2 sn sonra (chat zaten olaydan 2-4 sn geç tepki verir).
        Başlangıç: patlamadan ~11 sn önce. İkisi de yayıncının cümlesini ortadan bölmez."""
        from .spike import mesaj_puani
        sade = {"w", "gg", "?", "??", "???", "help"}
        tepki = sorted(t for t, _, m in is_.chat
                       if t >= is_.an - 2 and mesaj_puani(m)[0] > 1 and mesaj_puani(m)[1] not in sade)
        son = is_.sure
        if len(tepki) >= 4:
            # 3 sn'lik pencerelerde tepki yoğunluğu; zirvenin %35'inin altına düştüğü son yer
            yog = [(t, sum(1 for x in tepki if t <= x < t + 3)) for t in tepki]
            zirve = max(n for _, n in yog)
            canli = [t for t, n in yog if n >= max(2, zirve * 0.35)]
            if canli:
                son = canli[-1] + 3 + 2
        son = min(is_.sure, max(son, is_.an + 6))
        bas = max(0.0, is_.an - giris_sn)
        # KANCA: ilk saniyeler boş geçmesin (izleyici ilk 1-2 sn'de kaydırıp geçer). Yayıncı bu klipte konuşuyor
        # ama olaydan önceki girişte sessizse, girişi kısalt: olaydan ~4 sn önce başla.
        if segler and not any(e > bas + 0.5 and b < is_.an - 1 for b, e, _ in segler):
            bas = max(bas, is_.an - 4.0)
        for b, e, _ in segler:   # cümle ortasında kesme
            if b < son < e:
                son = min(is_.sure, e + 0.3) if e - son <= 5 else son
            if b < bas < e and bas - b <= 5:
                bas = max(0.0, b - 0.2)
        # izlenme süresi: kısa ve dolu klipler sonuna kadar izlenir (algoritmanın en önemli sinyali)
        # en fazla ~58 sn: Facebook 60 sn'yi geçen videoyu Reels değil normal GÖNDERİ yapıyor
        # (YouTube Shorts ve Instagram Reels için de en güvenli süre)
        if son - bas > 45:   # kısa ve dolu = sonuna kadar izlenir (Shorts/Reels'in en önemli sinyali)
            son = bas + 45
            for b, e, _ in segler:
                if b < son < e and e - son <= 2:
                    son = e + 0.3
        if son - bas < 15:   # çok kısa kalmasın ("yarıda kalmış" gibi durur)
            son = min(is_.sure, bas + 15)
            bas = max(0.0, son - 15)
        # SON KONTROL: yayıncı konuşurken bitmesin. Cümle uzatılamıyorsa (kayıt bitiyor / çok uzun)
        # cümlenin başından önce bitir — yarım kalan cümle "video yarıda bitti" hissi verir.
        for b, e, _ in sorted(segler, reverse=True):
            if b < son - 0.3 < e - 0.6:
                if e + 0.3 <= is_.sure and e - son <= 5 and e + 0.3 - bas <= 58.5:
                    son = e + 0.3
                elif b - 0.15 >= max(bas + 10, is_.an + 3):
                    son = b - 0.15
                break
        return bas, son

    @staticmethod
    def _gulme_orani(is_: "Is") -> float:
        """Gerçek tepki oranı (0-1): (1) mesaj sayısına değil FARKLI KİŞİLERE bakar (bir kişinin spam'i şişirmesin),
        (2) chat'in bu yayındaki NORMAL gülme oranını çıkarır (sürekli 'KEKW' yazan chat'lerde her an komik sayılmasın)."""
        from .spike import mesaj_puani
        sade = {"w", "gg", "?", "??", "???", "help"}

        def oran(lst):
            if not lst:
                return 0.0
            gul = [(k, m) for k, m in lst if mesaj_puani(m)[0] > 1 and mesaj_puani(m)[1] not in sade]
            mesaj = len(gul) / len(lst)
            gulen = len({k for k, _ in gul})
            kisi = gulen / max(1, len({k for k, _ in lst}))
            # en az 4 farklı kişi gülmeli: tek kişinin spam'i "herkes gülüyor" sayılmaz
            return (0.5 * mesaj + 0.5 * kisi) * min(1.0, gulen / 4)
        simdi = [(k, m) for t, k, m in is_.chat if is_.an - 3 <= t <= is_.an + 12]
        once = [(k, m) for t, k, m in is_.chat if t < is_.an - 5]
        g = oran(simdi)
        if len({k for k, _ in once}) >= 8:   # yeterince "normal an" verisi varsa ona göre düzelt
            taban = oran(once) * 0.6
            g = max(0.0, g - taban) / max(0.3, 1 - taban)
        return min(1.0, g)

    @staticmethod
    def _oyun_ani_mi(is_: "Is", ses_tepki: float, oyun_anlari: list) -> bool:
        """Komik olan oyundaki karakter mi? (patlama anında oyunda biri konuşuyor/bağırıyor + ses yükseliyor)"""
        yakin = [v for t, v in oyun_anlari if is_.an - 8 <= t <= is_.an + 4]
        # ara sahne değil: klibin çoğunda oyun altyazısı varsa bu sıradan bir ara sahne/diyalogdur
        genel = sum(v for _, v in oyun_anlari) / len(oyun_anlari) if oyun_anlari else 1.0
        return bool(yakin) and sum(yakin) / len(yakin) >= 0.3 and ses_tepki >= 5 and genel < 0.5

    @staticmethod
    def _bos_an_mi(is_: "Is", ses_tepki: float, oyun_anlari: list, yuz_t: float = 0.0,
                   oyun_ani: bool = False, aksiyon: float = 0.0) -> str:
        """Yapay zekâsız (ücretsiz) 'boş an' kontrolü. Boş string = iyi an."""
        from .spike import mesaj_puani
        yakin = [m for t, _, m in is_.chat if is_.an - 3 <= t <= is_.an + 12]
        # "W", "gg", "?" komiklik göstermez; gülme/şok tepkileri sayılır
        sade = {"w", "gg", "?", "??", "???", "help"}
        gulme = Uygulama._gulme_orani(is_)
        ara_sahne = (sum(v for _, v in oyun_anlari) / len(oyun_anlari)) if oyun_anlari else 0.0
        klip = sum(1 for m in yakin if mesaj_puani(m)[1] == "clip")
        # en az bir güçlü işaret lazım: chat gerçekten gülüyor / "clip" diyor / yayıncı bağırıyor ya da kamerada coşuyor
        # 1) chat gerçekten gülüyor/şaşırıyor ya da "clip" diyor  VE  2) yayıncı da tepki veriyor (bağırma / kamerada coşma)
        #    — chat çok güçlüyse (yarısından fazlası gülüyor) yayıncı sakin kalsa da olur
        # chat güçlü: gülüyor / "clip" diyor / herkes aynı şeyi yazıyor (yayıncı chat'e bir şey sordu vs.)
        chat_guclu = gulme >= 0.3 or klip >= 3 or (is_.spike.neden == "tekrar" and is_.spike.tekrar_oran >= 0.4)
        if is_.spike.neden == "ses":   # yayıncı bağırdı: chat'in biraz da olsa tepki vermesi yeter
            chat_guclu = chat_guclu or gulme >= 0.15
        yayinci_tepki = ses_tepki >= 6 or yuz_t >= 2.0 or gulme >= 0.5
        # ya da komik olan oyundaki karakter (bağıran/çıldıran NPC): yayıncı sakin kalsa da olur
        guclu = chat_guclu and (yayinci_tepki or oyun_ani or aksiyon >= 2.0)
        if not guclu:
            return (f"güzel an işareti yok (chat gülme %{int(gulme * 100)}, 'clip' {klip}, "
                    f"ses +{ses_tepki:.0f} dB, yüz {yuz_t:.1f}x)")
        if ara_sahne >= 0.6 and gulme < 0.5 and not oyun_ani:
            return f"çoğu oyunun ara sahnesi (%{int(ara_sahne * 100)}), chat'te pek gülme yok"
        return ""

    def _kalite_eler(self, skor: float, yz: int | None) -> str:
        """Boş string = geçti. Değilse elenme nedeni."""
        onceki = sorted(self._son_puanlar)
        self._son_puanlar.append(skor)
        if yz is not None and yz <= 3:
            return f"yapay zekâ 'boş an' dedi ({yz}/10)"
        esik = self._hedef_puan()
        # 3 saattir hiç klip geçmediyse biraz gevşet (stok tamamen boş kalmasın), ama 6'nın altına inme
        if time.time() - self._son_gecen > 3 * 3600:
            esik = max(6.0, esik - 1)
        if skor < esik:
            return f"puan {skor:.1f} < {esik:.1f}"
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
        self._kesim_gecmisi.append(time.time())
        if self.cfg.get("hazirlaniyor_bildirimi", True):
            try:
                await self._bildir(f"🎬 Klip hazırlanıyor: {iz.kanal.gorunen} ({iz.kanal.platform}) — "
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
                return await asyncio.wait_for(asyncio.to_thread(self.yaziya.coz, wav, is_.kanal.dil, True,
                                                                is_.kanal.gorunen), 240)
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
        if (cozum and cozum.guven >= 0.75 and len(segler) >= 2
                and self._dil_atla(cozum.asil_dil or cozum.dil)):
            log.info("klip elendi: yayıncı %s konuşuyor (hesapların: %s) — %s", cozum.dil,
                     ",".join(sorted(self._izinli_diller())), kid)
            self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
            if is_.kanal.platform != "youtube":
                self._yabanciya_ekle(is_.kanal.anahtar)
            return
        kaynak_dil = cozum.dil if cozum else ""
        zoom = float((self.cfg.get("klip") or {}).get("zoom", 1.3))
        ce = self.cfg.get("chat_ekrani") or {}
        # asıl olayın anı: chat 2-5 sn geç tepki verir; sesin zirvesi (bağırma/patlama/çarpma) olayı daha doğru gösterir
        zirve_t, zirve_db = await asyncio.to_thread(ses_zirvesi, is_.kaynak, is_.ofset, is_.sure, is_.an)
        if zirve_db >= 7 and abs(zirve_t - is_.an) > 0.5:
            log.info("🎯 olayın anı sesten bulundu: %.1f sn → %.1f sn (+%.0f dB)", is_.an, zirve_t, zirve_db)
            is_.an = zirve_t
        ses_tepki = await asyncio.to_thread(puan.an_tepkisi, is_.kaynak, is_.ofset, is_.sure, is_.an)
        duran = await asyncio.to_thread(hareketsiz_oran, is_.kaynak, is_.ofset, is_.sure, analiz.facecam)
        yuz_t = await asyncio.to_thread(yuz_tepkisi, is_.kaynak, is_.ofset, is_.sure, analiz.facecam, is_.an)
        # komik olan oyundaki karakter mi, yayıncı mı? (yayıncı coşmuyorsa ve oyunda biri bağırıyorsa: oyun anı)
        oyun_ani = self._oyun_ani_mi(is_, ses_tepki, oyun_anlari) and yuz_t < 2.0
        aksiyon = await asyncio.to_thread(oyun_aksiyonu, is_.kaynak, is_.ofset, is_.sure, analiz.facecam, is_.an)
        kalite, kalite_neden = self.kalite_puani(is_, ses_tepki, yuz_t, oyun_ani, duran, bool(segler), aksiyon,
                                                 segler)
        if duran >= 0.5:   # harita / menü / ayarlar: kimse izlemez
            log.info("klip elendi: oyun ekranı zamanın %%%d'inde duruyor (menü/harita) — %s", int(duran * 100), kid)
            self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
            return
        # yayıncı tepkisiz + sadece oyun (ara sahne / sinematik): izleyici için boş, puan ne olursa olsun atla
        konusma_sn = sum(max(0.0, e - b) for b, e, _ in segler)
        genel_oyun = (sum(1 for _, v in oyun_anlari if v) / len(oyun_anlari)) if oyun_anlari else 0.0
        if (konusma_sn < 2.0 and yuz_t < 1.8 and ses_tepki < 8 and aksiyon < 2.5
                and self._gulme_orani(is_) < 0.5):
            log.info("klip elendi: yayıncı tepkisiz (konuşma %.0f sn, yüz %.1fx), sadece oyun görüntüsü — %s",
                     konusma_sn, yuz_t, kid)
            self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
            return
        if genel_oyun >= 0.4 and konusma_sn < 4.0 and yuz_t < 2.0:
            log.info("klip elendi: oyunun ara sahnesi (%%%d), yayıncı neredeyse hiç konuşmuyor — %s",
                     int(genel_oyun * 100), kid)
            self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
            return
        # akıllı başlangıç/bitiş: tepki sönünce bitir, cümleyi bölme; boş kuyruk ve uzun giriş kesilir
        kb, ke = self._akilli_aralik(is_, segler)
        # kapkara kısımlar (yükleme ekranı, sahne geçişi) klipte kalmasın; çoğu karanlıksa hiç yapma
        karanlik = await asyncio.to_thread(karanlik_anlar, is_.kaynak, is_.ofset, is_.sure, analiz.facecam)
        if karanlik:
            kb2, ke2 = karanliktan_kirp(karanlik, kb, ke, is_.an)
            if (kb2, ke2) != (kb, ke):
                log.info("kapkara kısım kesildi: %.0f-%.0f → %.0f-%.0f sn", kb, ke, kb2, ke2)
                kb, ke = kb2, ke2
                for b, e, _ in sorted(segler, reverse=True):   # yeni bitişte de cümle bölünmesin
                    if b < ke - 0.3 < e - 0.6 and b - 0.15 > kb + 8:
                        ke = b - 0.15
                        break
            parca = karanlik[int(kb):int(ke)]
            if parca and sum(parca) / len(parca) > 0.3:
                log.info("klip elendi: görüntünün %%%d'i kapkara — %s", int(100 * sum(parca) / len(parca)), kid)
                self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
                return
        if ke - kb < 15:   # 15 sn'den kısa klipler "yarıda kalmış" gibi duruyor
            log.info("klip elendi: kırpınca çok kısa kaldı (%.0f sn) — %s", ke - kb, kid)
            self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
            return
        if kb > 0.5 or ke < is_.sure - 0.5:
            log.info("klip kırpıldı: %.0f sn → %.0f sn (baştan %.0f, sondan %.0f)", is_.sure, ke - kb, kb,
                     is_.sure - ke)
            is_.ofset += kb
            is_.sure = ke - kb
            is_.an -= kb
            is_.chat = [(t - kb, k, m) for t, k, m in is_.chat if kb <= t <= ke]
            segler = [(b - kb, e - kb, t) for b, e, t in segler if e > kb and b < ke]
            if cozum:
                cozum.segmentler = segler
                cozum.kelimeler = [type(w)(w.bas - kb, w.bit - kb, w.metin) for w in cozum.kelimeler
                                   if kb <= w.bas < ke]
                cozum.en_segler = [(b - kb, e - kb, t) for b, e, t in cozum.en_segler if e > kb and b < ke]
            oyun_anlari = [(t - kb, v) for t, v in oyun_anlari if kb <= t <= ke]
        # çıplaklık (GTA 6'da var): paylaşılırsa video kaldırılır, hesap ceza yer → asla paylaşma
        if self.cfg.get("ciplak_filtre", True):
            from .ciplak import ciplak_mi
            var, ne = await asyncio.to_thread(ciplak_mi, is_.kaynak, is_.ofset, is_.sure, is_.chat, segler)
            if var:
                log.info("klip elendi: çıplaklık var — %s — %s", ne, kid)
                self.sayac["elenen"] = self.sayac.get("elenen", 0) + 1
                return
        chat_pop = (chat_sec(is_.chat, is_.sure, 1, float(ce.get("sure_sn", 1.8)),
                             en_fazla=int(ce.get("en_fazla_mesaj", 5)), an=is_.an)
                    if ce.get("acik", True) else [])
        en_dusuk = float(self.cfg.get("en_dusuk_puan", 0))

        kareler = await asyncio.to_thread(self._kareler, is_) if self.yazar.client else []
        uretildi = False
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
            ceviri = None
            if cozum and segler and kaynak_dil and kaynak_dil != dil and not (
                    veri.get("altyazi") and len(veri["altyazi"]) == len(segler)):
                # ücretsiz çeviri: yayıncının kendi dilinden bu hesabın diline (Arapça -> Türkçe / İngilizce)
                ceviri = await asyncio.to_thread(ceviri_yap, [t for _, _, t in segler], dil, kaynak_dil)
                if ceviri:
                    veri["altyazi"] = ceviri
                    alt_not.append(f"yayıncı {kaynak_dil} konuşuyor → {dil} çevrildi")
                elif dil == "en" and cozum.en_segler:
                    alt_not.append(f"yayıncı {kaynak_dil} konuşuyor → en çevrildi (Whisper)")
                else:
                    alt_not.append(f"{kaynak_dil} → {dil} çeviri yapılamadı (internet?)")
            if (not veri.get("altyazi") and cozum and cozum.en_segler and dil == "en"
                    and kaynak_dil not in ("en", "tr")):
                alt = segment_parcala([x for x in cozum.en_segler if not oyun_konusmasi_mi(x[0], x[1], oyun_anlari)])
            elif veri.get("altyazi") and len(veri["altyazi"]) == len(segler) and kaynak_dil != dil:
                alt = segment_parcala([(b, e, t) for i, ((b, e, _), t) in enumerate(zip(segler, veri["altyazi"]))
                                       if i in secili])
            elif cozum and kaynak_dil != dil and kaynak_dil not in ("tr", "en") and not veri.get("altyazi"):
                alt = []   # çevrilemedi: yabancı dilde altyazı koyma (izleyici anlamaz)
            elif cozum and (kaynak_dil == dil or not veri.get("altyazi")):
                # aynı dil ya da çeviri yok: konuşma kendi dilinde, kelime kelime yazılır
                araliklar = [(segler[i][0] - 0.05, segler[i][1] + 0.05) for i in secili]
                alt = kelime_parcala([k for k in cozum.kelimeler
                                      if any(b <= (k.bas + k.bit) / 2 <= e for b, e in araliklar)])
            else:
                alt = segment_parcala([(b, e, t) for i, ((b, e, _), t) in
                                       enumerate(zip(segler, veri.get("altyazi", []))) if i in secili])
            # altyazı doğal yazımıyla kalır ("Oh my god"), büyük harfe çevrilmez
            if not self.yazar.client:
                # ücretsiz, profesyonel açıklama: yayıncının o anki sözü + anın türü (rastgele kalıp değil)
                from . import aciklama as acmod
                if veri.get("altyazi") and len(veri["altyazi"]) == len(segler) and kaynak_dil != dil:
                    hedef_seg = [(b, e, t) for i, ((b, e, _), t) in enumerate(zip(segler, veri["altyazi"])) if i in secili]
                elif kaynak_dil == dil:
                    hedef_seg = [x for i, x in enumerate(segler) if i in secili]
                elif dil == "en" and cozum and cozum.en_segler:
                    hedef_seg = list(cozum.en_segler)
                else:
                    hedef_seg = []
                tur = acmod.an_turu(self._gulme_orani(is_), aksiyon, ses_tepki, oyun_ani,
                                    is_.spike.neden == "tekrar")
                veri.update(acmod.yaz(dil, is_.kanal.gorunen, is_.kanal.platform, hedef_seg, is_.an, tur, hid,
                                      bool(facecam)))

            # 2) puan (senin beğenilerine göre ayarlanır)
            oz = puan.ozellik_cikar(is_.spike.kat, is_.chat, is_.sure, ses, analiz.aksiyon,
                                    sum(len(t.split()) for _, _, t in segler), bool(facecam),
                                    veri.get("puan") if self.yazar.client else None)
            skor_ogr, neden = self.ogrenci.puanla(hid, is_.kanal.gorunen.lower(), oz)
            # ücretsiz kalite puanı (anın kendisi) + senin ✅/🗑 kararlarından öğrenilen zevk
            # izlenme verisi biriktikçe öğrenilen zevkin payı artar (en fazla %50)
            pay = min(0.5, 0.2 + 0.015 * len(self.ogrenci.kararlilar()))
            skor = kalite if not self.ogrenci.w else round((1 - pay) * kalite + pay * skor_ogr, 1)
            ogr = neden if neden.startswith("sevdiğin tarz") else ""
            neden = " · ".join(x for x in (kalite_neden, ogr) if x)
            if oyun_ani:   # oyundaki karakterin şaşkınlığı/çıldırması: bu klipler öne çıksın
                skor = min(10.0, round(skor + 0.5, 1))
            hedef_kok = "bekleyen" if skor >= en_dusuk else "dusuk_puan"
            # sadece iyi anlar video olur: yapay zekâ "boş an" dediyse ya da son kliplerin zayıf yarısındaysa atla
            yz = veri.get("puan") if self.yazar.client else None
            elendi = self._kalite_eler(skor, yz) or (
                "" if yz is not None else self._bos_an_mi(is_, ses_tepki, oyun_anlari, yuz_t, oyun_ani, aksiyon))
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
            # (eski kurulumların config.yaml dosyasında yuzlu_duzen: "pip" yazıyor: yeni tarz için yeni ayar adı)
            duzen = (str(self.cfg.get("yuz_duzeni", "yarim")) if facecam
                     else str(self.cfg.get("yuzsuz_duzen", "tweet")))
            if duzen == "yarim" and not veri.get("baslik"):
                # ortadaki beyaz bant boş kalmasın: gerçek bilgi ("Yayıncı · GTA 6"), uydurma cümle yok
                veri["baslik"] = str(veri.get("aciklama") or f"{is_.kanal.gorunen} · GTA 6").strip("“”\"")[:48]
            tepki = None   # "chat koptu" gibi ekrana yazı ASLA basılmaz (kullanıcı istemedi)
            if oyun_ani and not facecam and self.cfg.get("pov_duzeni", True):
                # karakter anı (kamerası olmayan yayın): oyun tam ekran, üstte GTA VI + pembe POV yazısı,
                # yayıncı konuştuysa altyazısı yine altta
                duzen = "pov"
                # ekranda uydurma POV cümlesi yok: sadece yayıncının gerçek sözü (varsa) yazılır
                tepki = None
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
                            [] if duzen in ("pip", "pov", "yarim") else chat_pop, duzen, None, tepki)
                    # dramatik geçiş (siyah-beyaz + uğursuz ton): sadece ANİ şok/aksiyon anlarında, her videoda değil
                    from . import aciklama as _ac
                    _tur = _ac.an_turu(self._gulme_orani(is_), aksiyon, ses_tepki, oyun_ani,
                                       is_.spike.neden == "tekrar")
                    dram = bool(self.cfg.get("dram_efekt", True) and an is not None and zirve_db >= 10
                                and _tur in ("sok", "aksiyon"))
                    if dram:
                        log.info("🎬 dramatik geçiş eklendi (ani %s anı, +%.0f dB): %s", _tur, zirve_db, hid)
                    await asyncio.to_thread(dikey_video, is_.kaynak, is_.ofset, is_.sure, mp4, ass, zoom,
                                            None if duzen == "pov" else facecam,
                                            an, bool(self.cfg.get("ilerleme_cubugu", False)), duzen, dram)
            finally:
                ass.unlink(missing_ok=True)
            if not await asyncio.to_thread(video_saglam_mi, mp4):
                log.warning("çıkan video boş/bozuk, atlandı: %s", hid)
                shutil.rmtree(klasor, ignore_errors=True)
                continue
            # ilk saniye kancası: olay 3. sn'den sonraysa, en çarpıcı an videonun başında bir kez gösterilir
            ek = 0.0
            if self.cfg.get("ilk_saniye_kancasi", True) and is_.an >= 3.0 and is_.sure - is_.an >= 1.5:
                from .kurgu import on_izleme
                ek = await asyncio.to_thread(on_izleme, mp4, is_.an)
            soz = (veri.get("aciklama") or "") if (veri.get("aciklama") or "").startswith("“") else ""
            await asyncio.to_thread(self._kapak, mp4, soz or is_.kanal.gorunen, is_.an + ek, is_.sure + ek,
                                    "GTA 6", dil)
            metin = paylasim_metni(veri, is_.kanal, dil)
            # en çok izlenen GTA 6 Shorts'larındaki popüler etiket (GTA ile ilgili olan) açıklamaya eklenir
            tr_et = [e for e in self.trend.populer_etiketler(6) if "gta" in e and e not in veri.get("hashtagler", [])]
            if tr_et and veri.get("hashtagler"):
                veri["hashtagler"] = veri["hashtagler"][:3] + tr_et[:1] + veri["hashtagler"][3:]
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
                "surum": SURUM, "sure": round(is_.sure, 1),
                "facecam": bool(facecam), "chat_kat": round(is_.spike.kat, 1), "kelimeler": is_.spike.kelimeler,
                "transkript": [t for _, _, t in segler],
                "altyazi_notu": "; ".join(dict.fromkeys(alt_not)) or (f"{len(alt)} satır altyazı" if alt else "")}, ensure_ascii=False, indent=1), encoding="utf-8")
            self.sayac["klip"] += 1
            if hedef_kok == "dusuk_puan":
                log.info("düşük puan (%.1f < %.1f), Telegram'a yollanmadı: %s", skor, en_dusuk, hid)
                continue
            log.info("✅ klip hazır: %s (puan %.1f)", mp4, skor)
            if not uretildi:
                uretildi = True
                self._kabul_gecmisi.append(time.time())
            self._asama(is_.takip, "📤 Telegram'a gönderiliyor")
            await self._gonder(klasor)
            self._anlik_paylas_mi(hid, ad, skor)

    def _baslik_metni(self, bilgi: dict, metin: str, hid: str) -> str:
        p = float(bilgi.get("puan", 0) or 0)
        # 10 üzerinden puan + 5 yıldız (yarım yıldızlarla), kısa ve anlaşılır
        dolu = int(round(p / 2 * 2)) / 2
        yildiz = "★" * int(dolu) + ("½" if dolu % 1 else "") + "☆" * (5 - int(dolu + 0.5))
        etiket = "🔥 Çok iyi" if p >= 8.5 else "👍 İyi" if p >= 7 else "· Orta"
        if self._durum_oku().get("sade"):   # /sade: sadece puan (video zaten mesajın kendisi)
            return f"{yildiz}  {p:.1f}/10"
        plat = str(bilgi.get("platform", "")).capitalize()
        ust = (f"{yildiz}  {p:.1f}/10  {etiket}\n"
               f"🎮 {bilgi.get('yayinci', '')}" + (f" · {plat}" if plat and plat.lower() not in ("merge", "sekme", "sarkac") else "")
               + f" · {bilgi.get('hesap', '')}")
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
    def _klip_yeri(self, kid: str) -> tuple[str, Path] | None:
        """Klibin şu an nerede olduğu: bekleyen / hazir / paylasildi / dusuk_puan."""
        hesap = kid.rsplit("_", 1)[-1]
        for yer, yol in (("bekleyen", self.klasor / "bekleyen" / kid),
                         ("hazir", self.klasor / "hazir" / hesap / kid),
                         ("paylasildi", self.klasor / "paylasildi" / hesap / kid),
                         ("dusuk_puan", self.klasor / "dusuk_puan" / kid)):
            if yol.exists() and list(yol.glob("*.mp4")):
                return yer, yol
        return None

    async def _onay(self, kid: str) -> str:
        await asyncio.to_thread(self.ogrenci.karar, kid, "onay")
        yer = self._klip_yeri(kid)
        if not yer:
            raise RuntimeError("bu klibin dosyası artık yok (silinmiş ya da çok eski) — yeni gelen kliplerde dene")
        hesap = kid.rsplit("_", 1)[-1]
        hedef = self.klasor / "hazir" / hesap / kid
        if yer[0] == "paylasildi":
            return "Bu klip zaten paylaşılmış ✅"
        if yer[0] != "hazir":   # zaten sıradaysa taşımaya gerek yok
            hedef.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(yer[1]), str(hedef))
        self.sayac["onay"] += 1
        n = len(self.plan.stok(hesap))
        return f"✅ Sıraya eklendi ({hesap}). Sırada {n} video var, {self._aralik():g} saatte bir paylaşılıyor."

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
        "/kalite 7 — video olması için gereken en düşük puan (0-10)\n"
        "/paylasim — Instagram / YouTube otomatik paylaşım bağlı mı?\n"
        "/dene — paylaşım denemesi: hepsi gerçekten çalışıyor mu? (hiçbir şey yayınlanmaz)\n"
        "/anlik 8.5 — bu puan ve üstü klipler saat beklemeden hemen paylaşılsın\n"
        "/saatler — her gün hangi saatte hangi platforma paylaşılıyor\n"
        "/sade — kliplerde sadece video + puan görünsün · /detay — her şey görünsün\n"
        "/bagla — Instagram / YouTube hesabını Telegram'dan bağla (adım adım)\n"
        "/ikinci_bot — paylaşım kanalı (ikinci Telegram botu) kur\n"
        "/aralik 3 — kaç saatte bir paylaşılsın\n"
        "/tamotomatik — onayımı beklemeden en iyi klibi kendin paylaş (aç/kapat)\n"
        "/merge · /sekme · /sarkac — şimdi simülasyon videosu yap (her gün kendiliğinden de yapılır)\n"
        "/bugun — bugün paylaşılanlar\n"
        "/bildirim — bilgi mesajları (varsayılan kapalı: sadece videolar gelir) · /bildirim ac\n\n"
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
                    f"(en az {self._hedef_puan():g}/10 puan gerekiyor, /kalite) · şu an hazırlanan: "
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
        if komut in ("/ikinci_bot", "/paylasim_botu", "/paylaşım_botu"):
            tok = arg.strip()
            if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_\-]{30,}", tok):
                return ("📤 PAYLAŞIM KANALI KURULUMU\n1) Telegram'da @BotFather → /newbot → bir ad ver (ör. Klipçi Paylaşım)\n"
                        "2) Verdiği anahtarı buraya yaz:  /ikinci_bot 123456:ABC...\n3) Yeni bota /start yaz. Hepsi bu!")
            d = self._durum_oku()
            d["bot2_token"] = tok
            d.pop("bot2_chat", None)
            self._durum_yaz(d)
            self._bot2_kur(tok)
            g = asyncio.create_task(self.bot2.dinle())
            self._arka.add(g)
            return "✅ Paylaşım botu kuruldu. Şimdi YENİ bota gidip /start yaz."
        if komut in ("/merge", "/sekme", "/sarkac"):
            g = asyncio.create_task(self.merge_uret([komut.strip("/")]))
            self._arka.add(g)
            g.add_done_callback(self._arka.discard)
            return "🫧 Video hazırlanıyor (1-2 dk), bitince buraya gelecek."
        if komut in ("/sade", "/detay", "/detayli", "/detaylı"):
            d = self._durum_oku()
            d["sade"] = komut == "/sade"
            self._durum_yaz(d)
            return ("✅ Sade mod: kliplerde sadece video ve puan görünecek. Eski hâline dönmek için /detay"
                    if d["sade"] else "✅ Detaylı mod: puanın yanında yayıncı, neden ve açıklama da görünecek. Sade için /sade")
        if komut in ("/saatler", "/saat"):
            sabit = self._sabit_saatler()
            if not sabit:
                return f"Sabit saatler kapalı; {self._aralik():g} saatte bir paylaşılıyor."
            ikon = {"instagram": "📸", "facebook": "📘", "youtube": "▶️", "threads": "🧵"}
            satir = ["⏰ PAYLAŞIM SAATLERİ (Türkiye saati, her gün aynı)\n"]
            for h, lst in sabit.items():
                satir.append(f"[{h}] {len(lst)} video/gün")
                for saat, pl in lst:
                    satir.append(f"  {saat}  🎵" + "".join(ikon.get(p_, "") for p_ in pl))
                satir.append("")
            satir.append("🎵 TikTok her saatte (paylaşım kanalından elle). EN saatleri ABD izleyicisine göre.\n"
                         "Değiştirmek için config.yaml → paylasim_saatleri")
            return "\n".join(satir)
        if komut in ("/anlik", "/anlık"):
            try:
                n = float(arg.strip().replace(",", "."))
            except ValueError:
                return (f"⚡ Puanı {self._anlik_esik():g} ve üstü olan klipler saat beklemeden HEMEN paylaşılıyor "
                        f"(aynı hesaba en az 45 dk arayla).\nDeğiştirmek için: /anlik 9  ·  kapatmak için: /anlik 11")
            d = self._durum_oku()
            d["anlik_esik"] = n
            self._durum_yaz(d)
            return f"✅ Artık {n:g}+ puanlı klipler hemen paylaşılacak." if n <= 10 else "✅ Anında paylaşım kapatıldı."
        if komut in ("/dene", "/test_paylas", "/deneme"):
            g = asyncio.create_task(self._paylasim_denemesi())
            self._arka.add(g)
            g.add_done_callback(self._arka.discard)
            return ("🧪 Paylaşım denemesi başladı (1-3 dk). Hiçbir şey yayınlanmaz: Instagram'a gerçekten yüklenir ama "
                    "paylaşılmaz, diğerleri bağlantı kontrolü. Sonuç buraya gelecek.")
        if komut in ("/meta_tekrar", "/metatekrar"):
            d = self._durum_oku()
            d.pop("meta_engel", None)
            self._durum_yaz(d)
            self._son_tekrar = 0.0
            return ("✅ Meta engeli bekleme süresi sıfırlandı. Paylaşılamayan videolar birkaç dakika içinde tekrar "
                    f"denenecek ({len(self._durum_oku().get('tekrar') or [])} bekliyor).")
        if komut in ("/tamotomatik", "/tam_otomatik"):
            a = arg.strip().lower()
            if a in ("ac", "aç", "on", "kapat", "off"):
                d = self._durum_oku()
                d["tam_otomatik"] = a in ("ac", "aç", "on")
                self._durum_yaz(d)
            return ("🤖 Tam otomatik: " + ("AÇIK — her paylaşım saatinde en iyi klibi kendim seçip paylaşıyorum "
                                          "(senin ✅ bastıkların öncelikli)" if self._tam_otomatik()
                                          else "KAPALI — sadece senin ✅ bastıkların paylaşılır")
                    + "\n/tamotomatik ac · /tamotomatik kapat")
        if komut == "/aralik" or komut == "/aralık":
            try:
                n = float(arg.strip().replace(",", "."))
            except ValueError:
                return f"Şu an {self._aralik():g} saatte bir paylaşılıyor. Değiştirmek için: /aralik 3"
            if not 0.5 <= n <= 24:
                return "0.5 ile 24 saat arası yaz."
            d = self._durum_oku()
            d["aralik"] = n
            self._durum_yaz(d)
            return f"✅ Artık {n:g} saatte bir paylaşılacak (günde ~{self._gunluk()} video, hesap başına)."
        if komut in ("/bugun", "/bugün", "/paylasilanlar", "/paylaşılanlar"):
            return self._paylasim_ozeti(zaman.now().date(), "Bugün")
        if komut in ("/performans", "/izlenme"):
            await asyncio.to_thread(self.performans.guncelle, self._istatistik_cek)
            return self.performans.rapor()
        if komut in ("/trend", "/trendler"):
            if self.trend.eski_mi(1):
                await self._trend_guncelle()
            adlar = list({iz.kanal.gorunen or iz.kanal.ad for iz in self.izleyiciler.values()})
            adlar += [planmod.yayinci_adi(x.name) for x in (self.klasor / "bekleyen").glob("*")][:50]
            return self.trend.ozet(list(dict.fromkeys(adlar)))
        if komut in ("/bagla", "/bağla"):
            return await self._bagla(arg)
        if komut in ("/paylasim", "/paylaşım", "/otomatik"):
            return await asyncio.to_thread(self._paylasim_durumu)
        if komut in ("/bildirim", "/bildirimler"):
            a = arg.strip().lower()
            if a in ("ac", "aç", "on", "acik", "açık"):
                d = self._durum_oku()
                d["bildirim"] = True
                self._durum_yaz(d)
                return "🔔 Bilgi mesajları açıldı (açıldı, klip hazırlanıyor, stok raporu, altyazı durumu...)."
            if a in ("kapat", "kapa", "off", "kapali", "kapalı"):
                d = self._durum_oku()
                d["bildirim"] = False
                self._durum_yaz(d)
                return "🔕 Bilgi mesajları kapandı. Sadece videolar ve komutlarının cevapları gelecek."
            return (f"Bilgi mesajları şu an {'AÇIK 🔔' if self._bildirim_acik() else 'KAPALI 🔕'}.\n"
                    "/bildirim ac — aç · /bildirim kapat — kapat")
        if komut == "/kalite":
            if not arg.strip():
                return (f"Şu an sadece {self._hedef_puan():g}/10 ve üstü puan alan anlar video oluyor.\n"
                        f"Daha seçici: /kalite 8 · Daha çok video: /kalite 6")
            try:
                n = float(arg.strip().replace(",", "."))
            except ValueError:
                return "Sayı yaz: /kalite 7"
            if not 1 <= n <= 10:
                return "1 ile 10 arası bir puan yaz (önerilen 7)."
            d = self._durum_oku()
            d["kalite"] = n
            self._durum_yaz(d)
            return f"✅ Artık sadece {n:g}/10 ve üstü anlar video olacak."
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
        if tur == "by":   # 😍 bayıldım: en güçlü sinyal — öğren, yayıncıyı öne çıkar, klibi ilk sıraya al
            nedenler = await asyncio.to_thread(self.ogrenci.bayildi, kalan)
            d = self._durum_oku()
            fav = d.setdefault("favori", {})
            y = planmod.yayinci_adi(kalan)
            fav[y] = fav.get(y, 0) + 1
            self._durum_yaz(d)
            if self._klip_yeri(kalan) and (self._klip_yeri(kalan) or ("",))[0] == "bekleyen":
                await self._onay(kalan)
            ne = " + ".join(nedenler) if nedenler else "bu tarz an"
            cevap = (f"😍 Anladım! Bundan sonra böyle videolar öne çıkacak: {ne}"
                     f"{f' · {y} kliplerine öncelik' if y else ''}. Bu klip de ilk paylaşım saatinde gidiyor.")
            await self.bot.mesaj(cevap)
            return (cevap, None, [[{"text": "😍 Bayıldın — öğrenildi", "callback_data": "x:"}]])
        if tur == "bg":   # 👍 beğendim: zevkini öğren, klip yerinde kalsın (sonra paylaşabilirsin)
            await asyncio.to_thread(self.ogrenci.karar, kalan, "onay")
            return ("👍 Not aldım, bu tarzı seviyorsun", None,
                    [[{"text": "📤 Hemen paylaş", "callback_data": f"hp:{kalan}"[:64]},
                      {"text": "✅ Sıraya ekle", "callback_data": f"ok:{kalan}"[:64]}],
                     [{"text": "👍 Beğendin", "callback_data": "x:"}]])
        if tur == "hp":   # 📤 hemen paylaş — hemen cevap ver, yükleme arka planda (bitince sonuç mesajı gelir)
            planda = self.plan.bul(kalan)
            if (self._klip_yeri(kalan) or ("",))[0] == "paylasildi" or (
                    planda and planda[2].get("durum") in ("gonderildi", "paylasildi")):
                return ("Bu klip zaten paylaşılmış ✅", None, [[{"text": "✅ Paylaşıldı", "callback_data": "x:"}]])
            await self._onay(kalan)
            g = asyncio.create_task(self._hemen_paylas(kalan))
            self._arka.add(g)
            g.add_done_callback(self._arka.discard)
            return ("⏳ Paylaşılıyor", None,
                    [[{"text": "⏳ Yükleniyor… bitince sonuç mesajı gelecek", "callback_data": "x:"}]])
        if tur == "tt":   # paylaşım kanalında: TikTok'a da paylaştım
            await asyncio.to_thread(self.plan.platform_isaretle, kalan, "tiktok", "✅")
            return ("🎵 TikTok ✅", None, [[{"text": "🎵 TikTok'a paylaşıldı ✅", "callback_data": "x:"}]])
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
                self.plan.plan_yap(simdi.date(), hesaplar, adet, simdi, self._aralik(), self._tam_otomatik(),
                                   self._sabit_saatler())
                for hesap, it in self.plan.zamani_gelenler(simdi):
                    if not it.get("hid"):   # tam otomatik: şu an elimizdeki en iyi klibi seç
                        hid, neden = await asyncio.to_thread(self._en_iyi_aday, hesap, True)
                        if hid:
                            log.info("🏆 %s %s için en güzel bulduğum: %s (%s)", it.get("saat"), hesap, hid, neden)
                        if not hid:
                            self.plan.ata(simdi.date().isoformat(), hesap, it["saat"], "-", "bos")
                            log.info("⏰ %s %s: paylaşılacak yeterince iyi klip yok, bu saat atlandı", hesap, it["saat"])
                            continue
                        self._hazira_al(hid)
                        self.plan.ata(simdi.date().isoformat(), hesap, it["saat"], hid)
                        it = {**it, "hid": hid}
                    # ÖNCE işaretle: arada bir hata olsa bile aynı saat ikinci kez paylaşılmasın
                    self.plan.isaretle(it["hid"], "gonderildi", simdi.date().isoformat())
                    try:
                        await self._paylasim_hatirlat(hesap, it)
                    except Exception:  # noqa: BLE001
                        log.exception("paylaşım sırasında hata (%s %s) — bu saat tekrar denenmeyecek", hesap, it["saat"])
                if simdi.hour >= 10 and self._durum_oku().get("son_ozet") != simdi.date().isoformat():
                    d = self._durum_oku()
                    d["son_ozet"] = simdi.date().isoformat()
                    self._durum_yaz(d)
                    try:
                        await asyncio.to_thread(self.performans.guncelle, self._istatistik_cek)
                        await self._paylas_botu().mesaj(self._paylasim_ozeti(simdi.date() - timedelta(days=1), "Dün")
                                                        + "\n\n" + self.performans.rapor())
                    except Exception as e:  # noqa: BLE001
                        log.warning("günlük özet gönderilemedi: %r", e)
                if time.time() - self._son_tekrar > 20 * 60:
                    self._son_tekrar = time.time()
                    await self._tekrar_dene()
                if time.time() - self._son_istatistik > 6 * 3600:
                    self._son_istatistik = time.time()
                    n = await asyncio.to_thread(self.performans.guncelle, self._istatistik_cek)
                    if n:
                        log.info("📈 %d paylaşımın istatistiği güncellendi", n)
                        # izlenmeden öğren: çok izlenen anların özelliklerine benzeyen klipler daha yüksek puan alır
                        ogrenilen = await asyncio.to_thread(self.ogrenci.izlenme_isaretle, self.performans.iyi_kotu())
                        if ogrenilen:
                            log.info("🧠 %d klibin izlenme sonucu öğrenmeye eklendi", ogrenilen)
                if (self.cfg.get("gunluk_merge", True) and simdi.hour >= int(self.cfg.get("merge_saati", 11))
                        and self._durum_oku().get("son_merge") != simdi.date().isoformat()):
                    d = self._durum_oku()
                    d["son_merge"] = simdi.date().isoformat()
                    self._durum_yaz(d)
                    n = await self.merge_uret()
                    log.info("🫧 günün simülasyon videoları hazır: %d", n)
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
                        await self._bildir(f"🆕 Yeni sürüm var ({yerel} → {uzak}). Kurmak için /guncelle yaz.")
                rapor_saat = str(self.cfg.get("stok_rapor_saati", "21:30"))
                if simdi.strftime("%H:%M") >= rapor_saat and son_rapor != simdi.date().isoformat():
                    son_rapor = simdi.date().isoformat()
                    await self._bildir(self._stok_metni(yarin=True))
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

    async def merge_uret(self, turler: list[str] | None = None) -> int:
        """Günün simülasyon videoları: "merge" (birleşen toplar) ve "sekme" (her sekme = +1 top).
        Her açık hesap için kendi dilinde, seslendirmeli, seri numaralı. Sıraya yüksek puanla girer."""
        from . import merge as mg
        from . import sarkac as sr
        from . import sekme as sk
        turler = turler or list(self.cfg.get("gunluk_simulasyonlar") or ["merge", "sekme", "sarkac"])
        yapilan = 0
        for tur in turler:
            uret, baslik = {"merge": (mg.merge_video, "MERGE"), "sekme": (sk.sekme_video, "BOUNCE"),
                            "sarkac": (sr.sarkac_video, "PENDULUM")}.get(tur, (None, ""))
            if not uret:
                continue
            d = self._durum_oku()
            bolum = int(d.get(f"{tur}_bolum", 0)) + 1
            tur_yapilan = 0
            for h in self._hesaplar():
                hid = f"{zaman.now().strftime('%Y%m%d_%H%M%S')}_{tur}_{h['ad']}"
                klasor = self.klasor / "bekleyen" / hid
                klasor.mkdir(parents=True, exist_ok=True)
                mp4 = klasor / f"{hid}.mp4"
                try:
                    r = await asyncio.to_thread(uret, mp4, h["dil"], bolum)
                except Exception as e:  # noqa: BLE001
                    log.warning("%s videosu yapılamadı: %r", tur, e)
                    shutil.rmtree(klasor, ignore_errors=True)
                    continue
                kapak_baslik = {"merge": ("Boss'a kadar izle", "Wait for the boss"),
                                "sekme": ("Kaç topa ulaşacak?", "How many balls?"),
                                "sarkac": ("Kaç blok yapışacak?", "How many will stick?")}[tur][0 if h["dil"] == "tr" else 1]
                ad_k = {"sekme": ("SEKME", "BOUNCE"), "sarkac": ("SARKAÇ", "PENDULUM")}.get(
                    tur, ("MERGE", "MERGE"))[0 if h["dil"] == "tr" else 1]
                await asyncio.to_thread(self._kapak, mp4, kapak_baslik, 40.0, 50.0, f"{ad_k} #{bolum}", h["dil"])
                ac = r["aciklama"]
                ad_ = {"sekme": ("SEKME", "BOUNCE"), "sarkac": ("SARKAÇ", "PENDULUM")}.get(
                    tur, ("MERGE", "MERGE"))[0 if h["dil"] == "tr" else 1]
                pm = {"instagram": ac, "tiktok": ac, "youtube_baslik": f"{ad_} #{bolum} 😳 #shorts",
                      "youtube_aciklama": f"{ac} #shorts"}
                (klasor / "aciklama.json").write_text(json.dumps(pm, ensure_ascii=False, indent=1), encoding="utf-8")
                (klasor / "aciklama.txt").write_text(ac, encoding="utf-8")
                (klasor / "bilgi.json").write_text(json.dumps({
                    "yayinci": tur, "platform": tur, "hesap": h["ad"], "dil": h["dil"],
                    "puan": float(self.cfg.get("merge_puan", 8.0)),
                    "neden": f"günlük {ad_} #{bolum} (seslendirme: "
                             f"{'var' if r['seslendirme'] else 'yok — internet?'})"}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                tur_yapilan += 1
                await self._gonder(klasor)
            if tur_yapilan:
                d = self._durum_oku()
                d[f"{tur}_bolum"] = bolum
                self._durum_yaz(d)
            yapilan += tur_yapilan
        return yapilan

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

    BAGLA_YARDIM = (
        "🔗 HESAP BAĞLAMA (ücretsiz)\n\n"
        "📸 INSTAGRAM\n"
        "1) Instagram → Ayarlar → Hesap türü → Profesyonel hesaba geç (İçerik üreticisi)\n"
        "2) developers.facebook.com → Uygulama oluştur → 'Instagram'da içeriği yönet'\n"
        "3) Uygulama rolleri → Instagram Test Kullanıcısı ekle → Instagram'da daveti kabul et\n"
        "4) Instagram → 'Instagram girişi ile API kurulumu' → Erişim anahtarı oluştur → kopyala\n"
        "5) Buraya yaz:  /bagla instagram TR anahtar @kullaniciadi   (mesajın hemen silinir)\n"
        "   (Yeni uygulamalarda 'API setup with Unified login' → yapılandırma oluştur → anahtar oluştur)\n\n"
        "▶️ YOUTUBE\n"
        "1) console.cloud.google.com → Yeni proje → 'YouTube Data API v3' etkinleştir\n"
        "2) OAuth izin ekranı → Harici → Uygulamayı yayınla\n"
        "3) Kimlik bilgileri → OAuth istemci kimliği → 'TV ve Sınırlı Giriş Cihazları' → JSON indir\n"
        "4) O JSON dosyasını buraya gönder (dosya olarak)\n"
        "5) /bagla youtube TR yaz → sana bir kod gelir → telefonda google.com/device'a gir, kodu yaz, izin ver\n\n"
        "📘 FACEBOOK REELS: /bagla facebook  ·  🧵 THREADS: /bagla threads  (adımlar için yaz)\n"
        "Durum: /paylasim")

    async def _bagla(self, arg: str) -> str:
        from . import paylas
        p = arg.split()
        if len(p) < 2:
            return self.BAGLA_YARDIM
        plat, hesap = p[0].lower(), p[1].upper()
        if hesap not in {h["ad"] for h in self._hesaplar(hepsi=True)}:
            return f"Hesap adı TR ya da EN olmalı (yazdığın: {hesap})"
        if plat == "instagram":
            if len(p) < 3:
                return "Anahtarı da yaz:  /bagla instagram TR anahtar"
            ham = p[2].strip().strip('"\'<>`')
            if "…" in ham or "..." in ham:
                return ("⚠️ Anahtar yarım kopyalanmış (içinde '...' var). Meta'da 'Generate token' penceresindeki "
                        "KOPYALA butonunu kullan, yazıyı elle seçme.")
            if not re.fullmatch(r"[A-Za-z0-9_\-]{60,}", ham):
                return (f"⚠️ Bu bir anahtara benzemiyor ({len(ham)} karakter). Anahtar IGAA ya da EAA ile başlayan, "
                        "boşluksuz, 150+ karakterlik bir yazıdır. 'Generate token' penceresindeki kopyala butonunu kullan.")
            token = ham + (f"|{p[3].strip()}" if len(p) > 3 else "")
            try:
                k = await asyncio.to_thread(
                    lambda: paylas.Instagram(token, self.kok / "instagram" / f"{hesap}.json").hesap())
            except Exception as e:  # noqa: BLE001
                return f"⚠️ Bu anahtar çalışmadı: {e}"[:300]
            d = self._durum_oku()
            d.setdefault("ig_token", {})[hesap] = token
            self._durum_yaz(d)
            return f"✅ {hesap} hesabı Instagram'a bağlandı: @{k['kullanici']}\nReels'ler paylaşım saatinde kendiliğinden paylaşılacak."
        if plat in ("facebook", "threads"):
            if len(p) < 3:
                return (f"Anahtarı da yaz:  /bagla {plat} {hesap} anahtar" + ("  [sayfa adı]" if plat == "facebook" else "")
                        + "\nAdımlar için: /bagla")
            tok = p[2].strip().strip('"\'<>`')
            if not re.fullmatch(r"[A-Za-z0-9_\-]{60,}", tok):
                return "⚠️ Bu bir anahtara benzemiyor. Kopyala butonunu kullan, '...' ile biten yarım yazıyı alma."
            ek = " ".join(p[3:]).strip()
            try:
                if plat == "facebook":
                    tam = tok + (f"|{ek}" if ek else "")
                    s_ = await asyncio.to_thread(lambda: paylas.Facebook(tam).sayfa())
                    ad_ = s_["ad"]
                else:
                    tam = tok
                    k_ = await asyncio.to_thread(
                        lambda: paylas.Threads(tam, self.kok / "threads" / f"{hesap}.json").hesap())
                    ad_ = "@" + k_["kullanici"]
            except Exception as e:  # noqa: BLE001
                return f"⚠️ Bu anahtar çalışmadı: {e}"[:300]
            d = self._durum_oku()
            d.setdefault("fb_token" if plat == "facebook" else "th_token", {})[hesap] = tam
            self._durum_yaz(d)
            return f"✅ {hesap} hesabı {'Facebook' if plat == 'facebook' else 'Threads'}'e bağlandı: {ad_}"
        if plat == "youtube":
            istemci = self._yt_istemci(hesap)
            if not istemci.exists():
                return "Önce Google'dan indirdiğin JSON dosyasını buraya gönder (/bagla yaz, adımlar orada)."
            try:
                cihaz = await asyncio.to_thread(paylas.youtube_cihaz_baslat, istemci)
            except Exception as e:  # noqa: BLE001
                return f"⚠️ {e}"[:400]

            async def bekle():
                try:
                    await asyncio.to_thread(paylas.youtube_cihaz_bekle, istemci, cihaz,
                                            self.kok / "youtube" / f"{hesap}.json")
                    await self.bot.mesaj(f"✅ {hesap} hesabının YouTube kanalı bağlandı. Shorts'lar kendiliğinden yüklenecek.")
                except Exception as e:  # noqa: BLE001
                    await self.bot.mesaj(f"⚠️ YouTube bağlanamadı: {e}"[:300])
            g = asyncio.create_task(bekle())
            self._arka.add(g)
            g.add_done_callback(self._arka.discard)
            return (f"▶️ {hesap} için YouTube bağlama:\n1) Telefonda aç: {cihaz.get('verification_url')}\n"
                    f"2) Bu kodu yaz: {cihaz.get('user_code')}\n3) Kanalını seç → İzin ver\n"
                    "Bitince buraya ✅ mesajı gelecek.")
        return self.BAGLA_YARDIM

    async def _belge(self, icerik: bytes, ad: str, aciklama: str) -> str:
        """Telegram'dan gönderilen dosya: Google'ın YouTube anahtar dosyası (client_secret JSON)."""
        try:
            j = json.loads(icerik.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return "Bu dosyayı tanımadım. YouTube için Google'dan indirdiğin .json dosyasını gönder."
        if not (j.get("installed") or j.get("web")):
            return "Bu JSON Google OAuth dosyası değil (içinde 'installed' yok)."
        hesap = next((h["ad"] for h in self._hesaplar(hepsi=True) if h["ad"] in (aciklama or "").upper().split()), "")
        hedef = self.kok / "youtube" / (f"client_secret_{hesap}.json" if hesap else "client_secret.json")
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_bytes(icerik)
        return (f"✅ Google anahtar dosyası kaydedildi{' (' + hesap + ')' if hesap else ''}.\n"
                "Şimdi yaz:  /bagla youtube TR   (EN için /bagla youtube EN)")

    # ---------- anında paylaşım (çok yüksek puan) ----------
    def _kapak(self, mp4: Path, baslik: str, an: float, sure: float, etiket: str, dil: str) -> None:
        """Kapak resmi (kapak.jpg) + kapak karesinin zamanı (kapak.json). Olmazsa sessizce geç."""
        from .kapak import kapak_basa_ekle, kapak_yap
        try:
            r = kapak_yap(mp4, mp4.parent / "kapak.jpg", baslik, an, sure, etiket, dil)
            if r:
                ms = int(r[1] * 1000)
                # kapak videonun ilk anı olsun: TikTok/Instagram ilk kareyi kapak alır
                if self.cfg.get("kapak_basta", True) and kapak_basa_ekle(mp4, mp4.parent / "kapak.jpg"):
                    ms = 0
                (mp4.parent / "kapak.json").write_text(json.dumps({"ms": ms}), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.debug("kapak yapılamadı: %r", e)

    # platform başına günlük paylaşım sınırı (araştırma: Reels günde 1-3, Shorts'ta günün 2.'si sonrası düşer)
    # büyümek için daha sık paylaşım (API'lerin izin verdiği güvenli sınırlar: IG 50/gün, YouTube ~6/gün kota)
    GUNLUK_SINIR = {"instagram": 6, "facebook": 6, "threads": 5, "youtube": 5}

    def _platform_sinir(self, plat: str) -> int:
        ayar = self._durum_oku().get("gunluk_sinir") or self.cfg.get("gunluk_sinir") or {}
        return int(ayar.get(plat, self.GUNLUK_SINIR.get(plat, 3)))

    def _platform_sayi(self, hesap: str, plat: str, artir: bool = False) -> int:
        d = self._durum_oku()
        bugun = tarih.today().isoformat()
        sayac = {k: v for k, v in (d.get("plat_sayac") or {}).items() if k.startswith(bugun)}
        anahtar = f"{bugun}_{hesap}_{plat}"
        if artir:
            sayac[anahtar] = sayac.get(anahtar, 0) + 1
            d["plat_sayac"] = sayac
            self._durum_yaz(d)
        return sayac.get(anahtar, 0)

    def _anlik_esik(self) -> float:
        return float(self._durum_oku().get("anlik_esik", self.cfg.get("anlik_paylasim_puani", 8.5)))

    def _anlik_paylas_mi(self, hid: str, hesap: str, skor: float) -> bool:
        """Puanı çok yüksek (varsayılan 8.5+) klip saati beklemeden hemen paylaşılır.
        Aynı hesaba en az 'anlik_aralik_dk' (45 dk) arayla; arası dolmadıysa normal sıraya kalır (öncelikli)."""
        if not self._tam_otomatik() or skor < self._anlik_esik():
            return False
        if self._sabit_saatler() and not self.cfg.get("sabit_saatte_anlik", False):
            log.info("⚡ %s puan %.1f: sabit saat düzeni, bir sonraki paylaşım saatinde ilk o gidecek", hid, skor)
            return False
        d = self._durum_oku()
        son = (d.get("son_anlik") or {}).get(hesap, 0)
        if time.time() - son < float(self.cfg.get("anlik_aralik_dk", 45)) * 60:
            log.info("⚡ %s puan %.1f ama %s hesabına az önce paylaşıldı, sıraya girdi", hid, skor, hesap)
            return False
        d.setdefault("son_anlik", {})[hesap] = time.time()
        self._durum_yaz(d)
        log.info("⚡ puan %.1f ≥ %.1f: %s hemen paylaşılıyor", skor, self._anlik_esik(), hid)
        g = asyncio.create_task(self._hemen_paylas(hid))
        self._arka.add(g)
        g.add_done_callback(self._arka.discard)
        return True

    # ---------- paylaşılamayanları tekrar dene ----------
    def _tekrar_ekle(self, hid: str, hesap: str, plat: str) -> None:
        d = self._durum_oku()
        kuyruk = d.setdefault("tekrar", [])
        if not any(k["hid"] == hid and k["plat"] == plat for k in kuyruk):
            kuyruk.append({"hid": hid, "hesap": hesap, "plat": plat, "t": time.time(), "deneme": 0})
            self._durum_yaz(d)

    async def _tekrar_dene(self) -> int:
        """Bir platforma paylaşılamamış klipleri, platform tekrar çalışınca paylaş (en fazla 3 gün içinde, 6 deneme)."""
        d = self._durum_oku()
        kuyruk = [k for k in (d.get("tekrar") or []) if time.time() - k["t"] < 3 * 86400 and k["deneme"] < 6]
        if not kuyruk:
            if d.get("tekrar"):
                d["tekrar"] = []
                self._durum_yaz(d)
            return 0
        meta_engelli = time.time() < float(d.get("meta_engel", 0))
        yt_dolu = {h: (d.get("yt_sayac") or {}).get(f"{tarih.today().isoformat()}_{h}", 0)
                   >= int(self.cfg.get("youtube_gunluk", 6)) for h in {k["hesap"] for k in kuyruk}}
        basarili, kalan, islenen = [], [], 0
        for k in kuyruk:
            if islenen >= 4 or (k["plat"] in ("instagram", "facebook") and meta_engelli) or (
                    k["plat"] == "youtube" and yt_dolu.get(k["hesap"])):
                kalan.append(k)
                continue
            yer = self._klip_yeri(k["hid"])
            if not yer:
                continue   # dosya silinmiş: bırak
            klasor = yer[1]
            mp4 = next(iter(klasor.glob("*.mp4")), None)
            try:
                pm = json.loads((klasor / "aciklama.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pm = {}
            h = next((x for x in self._hesaplar(hepsi=True) if x["ad"] == k["hesap"]), {})
            f = {"instagram": self._ig_paylas, "facebook": self._fb_paylas, "youtube": self._yt_paylas}[k["plat"]]
            islenen += 1
            sonuc = await asyncio.to_thread(f, h, k["hesap"], mp4, pm)
            v = str(sonuc.get(k["plat"], "HATA: bağlı değil"))
            if v.startswith("HATA"):
                k["deneme"] += 1
                kalan.append(k)
                if "api access blocked" in v.lower():
                    d2 = self._durum_oku()
                    d2["meta_engel"] = time.time() + 12 * 3600
                    self._durum_yaz(d2)
                    meta_engelli = True
                continue
            self.plan.platform_isaretle(k["hid"], k["plat"], v)
            basarili.append((k, v))
        d = self._durum_oku()
        d["tekrar"] = kalan
        self._durum_yaz(d)
        if basarili:
            ikon = {"instagram": "📸 Instagram", "facebook": "📘 Facebook", "youtube": "▶️ YouTube"}
            try:
                await self._paylas_botu().mesaj("♻️ Daha önce paylaşılamayanlar şimdi paylaşıldı:\n" + "\n".join(
                    f"{ikon[k['plat']]} [{k['hesap']}] {planmod.yayinci_adi(k['hid'])}: ✅ {v}" for k, v in basarili))
            except Exception as e:  # noqa: BLE001
                log.warning("tekrar bildirimi gönderilemedi: %r", e)
        return len(basarili)

    def _deneme_videosu(self) -> Path:
        """3 saniyelik küçük deneme videosu (Instagram kurallarına uygun)."""
        yol = self.klasor / "_is" / "deneme.mp4"
        if not yol.exists():
            yol.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([arac("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3",
                            "-f", "lavfi", "-i", "sine=f=440:d=3", "-shortest", "-c:v", "libx264", "-profile:v", "high",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
                            str(yol)], check=True, creationflags=_PENCERESIZ, timeout=120)
        return yol

    def _paylasim_denemesi_ic(self) -> str:
        from . import paylas
        satir = ["🧪 PAYLAŞIM DENEMESİ (hiçbir şey yayınlanmadı)\n"]
        engel = float(self._durum_oku().get("meta_engel", 0))
        if time.time() < engel:
            satir.append("⏸ Meta engeli beklemesi aktif — deneme yine de yapılıyor\n")
        try:
            video = self._deneme_videosu()
        except Exception as e:  # noqa: BLE001
            return f"Deneme videosu yapılamadı: {e}"
        for h in self._hesaplar(hepsi=True):
            ad = h["ad"]
            s_ = [f"[{ad}]"]
            if h.get("instagram_token"):
                try:
                    ig = paylas.Instagram(h["instagram_token"], self.kok / "instagram" / f"{ad}.json", bekle=3)
                    k = ig.hesap()
                    s_.append(f"📸 Instagram (@{k['kullanici']}): ✅ {ig.deneme(video)}")
                except Exception as e:  # noqa: BLE001
                    s_.append(f"📸 Instagram: ❌ {e}"[:220])
            else:
                s_.append("📸 Instagram: — bağlı değil")
            if h.get("facebook_token"):
                try:
                    s_.append(f"📘 Facebook: ✅ sayfa erişimi tamam ({paylas.Facebook(h['facebook_token']).sayfa()['ad']})")
                except Exception as e:  # noqa: BLE001
                    s_.append(f"📘 Facebook: ❌ {e}"[:220])
            if h.get("threads_token"):
                try:
                    k = paylas.Threads(h["threads_token"], self.kok / "threads" / f"{ad}.json").hesap()
                    s_.append(f"🧵 Threads: ✅ @{k['kullanici']}")
                except Exception as e:  # noqa: BLE001
                    s_.append(f"🧵 Threads: ❌ {e}"[:220])
            yt = paylas.YouTube(self._yt_istemci(ad), self.kok / "youtube" / f"{ad}.json")
            if yt.bagli_mi():
                try:
                    s_.append(f"▶️ YouTube: ✅ kanal: {yt.kanal()}")
                except Exception as e:  # noqa: BLE001
                    s_.append(f"▶️ YouTube: ❌ {e}"[:220])
            satir.append("\n".join(s_) + "\n")
        if any("access blocked" in x.lower() for x in satir):
            satir.append("⚠️ 'API access blocked' = Meta geliştirici hesabını kilitlemiş. Bilgisayardan "
                         "developers.facebook.com/apps → Confirm Account ile doğrula, sonra /meta_tekrar.")
        elif not any("❌" in x for x in satir):
            satir.append("🎉 Hepsi çalışıyor!")
            d = self._durum_oku()
            d.pop("meta_engel", None)
            self._durum_yaz(d)
        return "\n".join(satir)

    async def _paylasim_denemesi(self) -> None:
        try:
            sonuc = await asyncio.to_thread(self._paylasim_denemesi_ic)
        except Exception as e:  # noqa: BLE001
            sonuc = f"Deneme yapılamadı: {e!r}"[:300]
        bekleyen = len(self._durum_oku().get("tekrar") or [])
        if "Hepsi çalışıyor" in sonuc and bekleyen:
            sonuc += f"\n♻️ Daha önce paylaşılamayan {bekleyen} paylaşım şimdi tekrar deneniyor."
        await self.bot.mesaj(sonuc)
        if "Hepsi çalışıyor" in sonuc and bekleyen:
            await self._tekrar_dene()

    def _paylasim_durumu(self) -> str:
        from . import paylas
        satir = ["🤖 OTOMATİK PAYLAŞIM\n"]
        for h in self._hesaplar(hepsi=True):
            ad = h["ad"]
            if h.get("instagram_token"):
                try:
                    k = paylas.Instagram(h["instagram_token"], self.kok / "instagram" / f"{ad}.json").hesap()
                    ig = f"✅ bağlı (@{k['kullanici']})"
                except Exception as e:  # noqa: BLE001
                    ig = f"⚠️ anahtar çalışmıyor: {e}"[:150]
            else:
                ig = "❌ bağlı değil (config.yaml → hesaplar → instagram_token)"
            yt = paylas.YouTube(self._yt_istemci(ad), self.kok / "youtube" / f"{ad}.json")
            ytd = ("✅ bağlı" if yt.bagli_mi() else
                   "❌ bağlı değil (YOUTUBE_BAGLA.bat)" if self._yt_istemci(ad).exists() else
                   "❌ bağlı değil (önce youtube/client_secret.json)")
            if h.get("facebook_token"):
                try:
                    sy = paylas.Facebook(h["facebook_token"]).sayfa()
                    fb = f"✅ bağlı (sayfa: {sy['ad']})"
                except Exception as e:  # noqa: BLE001
                    fb = f"⚠️ çalışmıyor: {e}"[:160]
            else:
                fb = "❌ bağlı değil (/bagla facebook)"
            th = "✅ bağlı" if h.get("threads_token") else "❌ bağlı değil (/bagla threads)"
            satir.append(f"[{ad}]\n📸 Instagram: {ig}\n▶️ YouTube: {ytd}\n📘 Facebook: {fb}\n🧵 Threads: {th}\n"
                         f"🎵 TikTok: elle (paylaşım kanalına gelir)\n")
        satir.append("Bağlı olanlara paylaşım saatinde kendisi yükler. Kurulum: README → OTOMATİK PAYLAŞIM")
        return "\n".join(satir)

    def _yt_istemci(self, hesap: str = "") -> Path:
        """Hesaba özel (client_secret_TR.json) varsa o — her Google projesinin günlük ~6 yükleme hakkı ayrı."""
        ozel = self.kok / "youtube" / f"client_secret_{hesap}.json"
        return ozel if hesap and ozel.exists() else self.kok / "youtube" / "client_secret.json"

    def _otomatik_paylas(self, hesap: str, mp4: Path, pm: dict, izinli: list | None = None) -> dict:
        """Bağlı platformlara AYNI ANDA yükle (Instagram→Threads zinciri, Facebook, YouTube paralel).
        {platform: link ya da 'HATA: ...'}"""
        from concurrent.futures import ThreadPoolExecutor
        h = next((x for x in self._hesaplar(hepsi=True) if x["ad"] == hesap), {})
        # Meta "API erişimi engellendi" dediyse bir süre Meta platformlarını hiç deneme (durumu kötüleştirmesin)
        engel = float(self._durum_oku().get("meta_engel", 0))
        if time.time() < engel:
            kalan = int((engel - time.time()) / 3600) + 1
            h = {**h, "instagram_token": "", "facebook_token": "", "threads_token": ""}
            log.info("Meta (Instagram/Facebook/Threads) erişimi engelli, ~%d saat daha denenmeyecek", kalan)
        # günlük sınırı dolan platform bugün atlanır (hesabı spam gibi göstermesin; fazla video TikTok'a kalır)
        dolu = {p_: self._platform_sayi(hesap, p_) >= self._platform_sinir(p_)
                for p_ in ("instagram", "facebook", "threads", "youtube")}
        if izinli is not None:   # sabit saat: bu saatte sadece belirlenen platformlar
            dolu = {p_: dolu[p_] or p_ not in izinli for p_ in dolu}
        if dolu["instagram"]:
            h = {**h, "instagram_token": ""}
        if dolu["facebook"]:
            h = {**h, "facebook_token": ""}
        if dolu["threads"]:
            h = {**h, "threads_token": ""}
        if dolu["youtube"]:
            h = {**h, "youtube": False}
        isler = [self._ig_paylas, self._fb_paylas, self._yt_paylas]
        sonuc: dict = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            for r in ex.map(lambda f: f(h, hesap, mp4, pm), isler):
                sonuc.update(r)
        # Threads videoyu bir adresten alır: önce Instagram'ın, olmazsa Facebook'un kopyası
        if h.get("threads_token") and (sonuc.get("_ig_adres") or sonuc.get("_fb_id")):
            from . import paylas
            adresler = [sonuc.pop("_ig_adres", "")]
            if sonuc.get("_fb_id"):
                try:
                    adresler.append(paylas.Facebook(h["facebook_token"]).video_adresi(sonuc["_fb_id"]))
                except Exception as e:  # noqa: BLE001
                    log.debug("facebook video adresi alınamadı: %r", e)
            try:
                th = paylas.Threads(h["threads_token"], self.kok / "threads" / f"{hesap}.json", bekle=3)
                sonuc["threads"] = th.video(adresler, pm.get("instagram", ""))
                log.info("🧵 Threads'e paylaşıldı (%s): %s", hesap, sonuc["threads"])
            except Exception as e:  # noqa: BLE001
                log.warning("Threads paylaşımı olmadı (%s): %r", hesap, e)
                sonuc["threads"] = f"HATA: {e}"[:200]
        sonuc.pop("_ig_adres", None)
        sonuc.pop("_fb_id", None)
        for p_, v in sonuc.items():
            if p_ in self.GUNLUK_SINIR and str(v).startswith("http"):
                self._platform_sayi(hesap, p_, artir=True)
        for p_ in ("instagram", "facebook", "youtube"):
            if dolu[p_] and p_ not in sonuc and (izinli is None or p_ in izinli):
                sonuc[p_] = f"SINIR: bugünkü {p_} sınırı ({self._platform_sinir(p_)}) doldu, hesap korunuyor"
        if any("api access blocked" in str(v).lower() for v in sonuc.values()):
            d = self._durum_oku()
            d["meta_engel"] = time.time() + 12 * 3600
            self._durum_yaz(d)
            log.warning("Meta API erişimini engelledi: 12 saat Instagram/Facebook/Threads denenmeyecek")
            for p_ in ("instagram", "facebook", "threads"):
                if str(sonuc.get(p_, "")).startswith("HATA") or p_ not in sonuc:
                    if h.get(f"{p_}_token") or p_ in sonuc:
                        sonuc[p_] = ("HATA: Meta uygulamanın erişimini engelledi (API access blocked). 12 saat "
                                     "denenmeyecek — developers.facebook.com'da Klip uygulamasındaki uyarılara bak")
        return sonuc

    def _ig_paylas(self, h: dict, hesap: str, mp4: Path, pm: dict) -> dict:
        from . import paylas
        if not h.get("instagram_token"):
            return {}
        ig = paylas.Instagram(h["instagram_token"], self.kok / "instagram" / f"{hesap}.json", bekle=3)
        son_hata: Exception | None = None
        for deneme, video in enumerate((mp4, None)):
            try:
                if video is None:   # ilk deneme reddedildiyse: Instagram'ın kurallarına tam uygun kopya ile tekrar
                    video = guvenli_kopya(mp4)
                    log.info("Instagram videoyu reddetti, uyumlu kopya ile tekrar deneniyor (%s)", hesap)
                try:
                    kapak_ms = json.loads((Path(mp4).parent / "kapak.json").read_text(encoding="utf-8"))["ms"]
                except (OSError, ValueError, KeyError):
                    kapak_ms = None
                link = ig.reels(video, pm.get("instagram", ""), kapak_ms) or "paylaşıldı"
                log.info("📸 Instagram'a paylaşıldı (%s): %s", hesap, link)
                return {"instagram": link, "_instagram_id": ig.son_medya_id, "_ig_adres": ig.son_video_adresi}
            except Exception as e:  # noqa: BLE001
                son_hata = e
                if "token" in str(e).lower() or "permission" in str(e).lower():
                    break   # anahtar sorunu: tekrar denemenin anlamı yok
        log.warning("Instagram paylaşımı olmadı (%s): %r", hesap, son_hata)
        return {"instagram": f"HATA: {son_hata}"[:200]}

    def _fb_paylas(self, h: dict, hesap: str, mp4: Path, pm: dict) -> dict:
        from . import paylas
        if not h.get("facebook_token"):
            return {}
        try:
            from .kurgu import facebook_kopya
            fb = paylas.Facebook(h["facebook_token"])
            link = fb.reels(facebook_kopya(mp4), pm.get("instagram", ""))
            log.info("📘 Facebook'a paylaşıldı (%s): %s", hesap, link)
            return {"facebook": link, "_fb_id": fb.son_video_id}
        except Exception as e:  # noqa: BLE001
            log.warning("Facebook paylaşımı olmadı (%s): %r", hesap, e)
            return {"facebook": f"HATA: {e}"[:200]}

    def _yt_paylas(self, h: dict, hesap: str, mp4: Path, pm: dict) -> dict:
        from . import paylas
        yt = paylas.YouTube(self._yt_istemci(hesap), self.kok / "youtube" / f"{hesap}.json")
        if not (h.get("youtube", True) and yt.bagli_mi()):
            return {}
        d = self._durum_oku()
        sayac = d.get("yt_sayac") or {}
        anahtar = f"{tarih.today().isoformat()}_{hesap}"
        if sayac.get(anahtar, 0) >= int(self.cfg.get("youtube_gunluk", 6)):
            return {"youtube": "HATA: bugünkü YouTube yükleme hakkı doldu (Google sınırı), elle yükle"}
        try:
            etiket = [t for t in pm.get("youtube_aciklama", "").split() if t.startswith("#")]
            link = yt.yukle(mp4, pm.get("youtube_baslik", ""), pm.get("youtube_aciklama", ""), etiket)
            kapak = Path(mp4).parent / "kapak.jpg"
            if kapak.exists():   # Shorts kapağı: YouTube videoyu işledikten sonra kabul eder, arka planda dener
                import threading
                threading.Thread(target=yt.kapak_koy, args=(link.rsplit("/", 1)[-1], kapak), daemon=True).start()
            d = self._durum_oku()
            sayac = {k: v for k, v in (d.get("yt_sayac") or {}).items() if k.startswith(tarih.today().isoformat())}
            sayac[anahtar] = sayac.get(anahtar, 0) + 1
            d["yt_sayac"] = sayac
            self._durum_yaz(d)
            log.info("▶️ YouTube'a yüklendi (%s): %s", hesap, link)
            return {"youtube": link}
        except Exception as e:  # noqa: BLE001
            log.warning("YouTube yüklemesi olmadı (%s): %r", hesap, e)
            return {"youtube": f"HATA: {e}"[:200]}

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
        izinli = it.get("platformlar") if isinstance(it.get("platformlar"), list) else None
        oto = await asyncio.to_thread(self._otomatik_paylas, hesap, mp4, pm, izinli)
        kimlik = {"instagram": oto.pop("_instagram_id", ""),
                  "youtube": oto["youtube"].rsplit("/", 1)[-1] if str(oto.get("youtube", "")).startswith("http") else ""}
        if any(kimlik.values()):
            self.performans.kaydet(it["hid"], hesap, planmod.yayinci_adi(it["hid"]), kimlik)
        for plat, v in oto.items():
            self.plan.platform_isaretle(it["hid"], plat, v)
            if str(v).startswith("HATA") and plat in ("instagram", "facebook", "youtube"):
                self._tekrar_ekle(it["hid"], hesap, plat)
        durum_satir = []
        for ad_, ikon in (("instagram", "📸 Instagram"), ("facebook", "📘 Facebook"), ("threads", "🧵 Threads"),
                          ("youtube", "▶️ YouTube")):
            if ad_ in oto:
                v_ = oto[ad_]
                durum_satir.append(f"{ikon}: " + ("⚠️ " + v_[6:] if v_.startswith("HATA") else
                                                  "⏸ " + v_[7:] if v_.startswith("SINIR") else "✅ paylaşıldı " + v_))
        elle = [p for p in ("instagram", "tiktok", "youtube") if p == "tiktok" or (
                (izinli is None or p in izinli) and (not oto.get(p) or str(oto.get(p, "")).startswith(("HATA", "SINIR"))))]
        bot = self._paylas_botu()
        try:
            await bot.video_gonder(mp4, f"📤 {hesap} — {it['saat']}  ({planmod.yayinci_adi(it['hid'])})\n"
                                             + ("\n".join(durum_satir) + "\n" if durum_satir else "")
                                             + "Elle yükle: " + ", ".join(
                                                 {"instagram": "Instagram", "tiktok": "TikTok",
                                                  "youtube": "YouTube"}[p] for p in elle), it["hid"],
                                        butonlar=[[{"text": "🎵 TikTok'a paylaştım", "callback_data": f"tt:{it['hid']}"[:64]}],
                                                  [{"text": "✅ Hepsi tamam", "callback_data": f"pd:{it['hid']}"[:64]},
                                                   {"text": "⏭ Atla", "callback_data": f"pa:{it['hid']}"[:64]}]])
            parca = [f"<b>⏰ {escape(hesap)} — {it['saat']}</b>  (metne dokun → kopyalanır)"]
            for baslik, anahtar, plat in (("📸 Instagram", "instagram", "instagram"), ("🎵 TikTok", "tiktok", "tiktok"),
                                          ("▶️ YouTube başlık", "youtube_baslik", "youtube"),
                                          ("▶️ YouTube açıklama", "youtube_aciklama", "youtube")):
                if pm.get(anahtar) and plat in elle:
                    parca.append(f"{baslik}:\n<code>{escape(pm[anahtar])}</code>")
            await bot.html("\n\n".join(parca))
            kapak = k / "kapak.jpg"
            if kapak.exists() and "tiktok" in elle:
                try:
                    await bot.foto_gonder(kapak, "🖼 Kapak — TikTok'a yüklerken: Kapak → Fotoğraf yükle / bu kareyi seç")
                except Exception as e:  # noqa: BLE001
                    log.debug("kapak gönderilemedi: %r", e)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("paylaşım hatırlatması gönderilemedi: %r", e)
            return False

    async def _hemen_paylas(self, kid: str) -> str:
        """📤 Hemen paylaş: sırayı beklemeden şimdi Instagram/YouTube'a yükle, TikTok için paylaşım kanalına gönder."""
        hesap = kid.rsplit("_", 1)[-1]
        self._hazira_al(kid)   # klip hâlâ "bekleyen"deyse (anında paylaşım) paylaşılacaklar klasörüne al
        simdi = zaman.now()
        it = {"hid": kid, "saat": simdi.strftime("%H:%M"), "durum": "gonderildi"}
        self.plan.ekle(simdi.date(), hesap, kid, it["saat"], "gonderildi")
        ok = await self._paylasim_hatirlat(hesap, it)
        return "📤 Paylaşılıyor — sonucu paylaşım kanalında göreceksin" if ok else "⚠️ Paylaşılamadı, tekrar dene"

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
                    await self._bildir("⏳ Altyazı aracı 10 dakikadır hazırlanıyor (model iniyor olabilir). "
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
                    await self._bildir("⚠️ Konuşma altyazısı hazırlanamadı, videolar altyazısız gelecek.\n"
                                         f"Neden: {self.yaziya.durum}" + ek)
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(300)
        bekci.cancel()
        try:
            await self._bildir(f"✅ Altyazı aracı hazır ({self.yaziya.durum}). Klipler artık altyazılı gelecek.")
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
        if self.bot2:
            gorevler.append(asyncio.create_task(self.bot2.dinle()))
        gorevler += [asyncio.create_task(self.isci()) for _ in range(n_isci)]
        gorevler.append(asyncio.create_task(self.gonderici()))
        gorevler.append(asyncio.create_task(self._hazirlik()))
        gorevler.append(asyncio.create_task(self.planci()))
        gorevler.append(asyncio.create_task(self.hiz_ayari()))
        gorevler.append(asyncio.create_task(self.saglik_ayari()))
        gorevler.append(asyncio.create_task(self.trend_dongu()))
        try:
            await self.bot.komut_menusu()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._bildir(f"▶ {OYUN.kisa} Klipçi açıldı (sürüm {SURUM}). Yayınlar aranıyor... (/durum)")
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram'a ulaşılamadı: %s", e)
        try:
            await asyncio.gather(*gorevler)
        finally:
            for a in list(self.izleyiciler):
                await self._birak(a)
