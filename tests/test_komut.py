import asyncio

from klipci import kesif
from klipci.uygulama import Uygulama


def _app(tmp_path, monkeypatch):
    monkeypatch.setattr(kesif, "kick_bilgi", lambda ad: {"canli": True, "chatroom_id": 1})
    monkeypatch.setattr(kesif, "yayinda_mi", lambda k: False)
    monkeypatch.setattr(kesif, "youtube_kanal_canli", lambda h: None)
    cfg = {"telegram": {"bot_token": "x"}, "klasor": str(tmp_path / "k"),
           "kanallar": {"twitch": ["xqc"], "yasakli": ["kotu"]}, "altyazi": {"acik": False}}
    return Uygulama(cfg, tmp_path)


def test_ekle_cikar_yasakla(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    assert "eklendi" in run("/ekle kick adinross") and "yayında" in run("/ekle kick adinross")
    assert "eklendi" in run("https://www.twitch.tv/KaiCenat")
    assert "değil" in run("/ekle twitch kaicenat")
    assert u._liste("kick") == ["adinross"]
    assert u._liste("twitch") == ["xqc", "kaicenat"]
    assert "çıkarıldı" in run("/cikar twitch xqc")
    assert u._liste("twitch") == ["kaicenat"]
    assert "yasaklandı" in run("/yasakla adinross")
    assert {"kotu", "adinross"} <= u._yasaklar()
    assert "kaldırıldı" in run("/yasak_kaldir adinross")
    liste = run("/liste")
    assert "kaicenat" in liste and "kotu" in liste
    assert "/twitch" in run("/yardim")
    assert run("selam") == ""
    # kalıcı: yeni uygulama aynı listeyi görür
    assert _app(tmp_path, monkeypatch)._liste("twitch") == ["kaicenat"]


def test_isim_hesap_plan_butonlar(tmp_path, monkeypatch):
    import json
    from datetime import datetime
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    assert [h["ad"] for h in u._hesaplar()] == ["TR", "EN"]
    assert "tüm hesaplar" in run("/isim gta6klipleri")
    assert all(h["imza"] == "@gta6klipleri" for h in u._hesaplar())
    assert "EN" in run("/isim en @gta6clips")
    assert {h["ad"]: h["imza"] for h in u._hesaplar()} == {"TR": "@gta6klipleri", "EN": "@gta6clips"}
    cevap, _, _ = asyncio.run(u._buton("hs:EN"))
    assert "kapandı" in cevap and [h["ad"] for h in u._hesaplar()] == ["TR"]
    cevap, _, _ = asyncio.run(u._buton("hs:TR"))
    assert "En az bir" in cevap
    cevap, _, _ = asyncio.run(u._buton("pl:kick"))
    assert "kapandı" in cevap and not u._platform_acik_mi("kick")
    assert "kapandı" in asyncio.run(u._buton("pl:oto"))[0] and not u._oto_acik_mi()
    # stok + plan + paylaştım
    for i in range(3):
        k = u.klasor / "hazir" / "TR" / f"20261119_10000{i}_kai{i}_TR"
        k.mkdir(parents=True)
        (k / "a.mp4").write_bytes(b"x")
        (k / "bilgi.json").write_text(json.dumps({"puan": 5 + i}))
    assert "TR: 3 video" in run("/stok")
    u.plan.plan_yap(datetime.now().date(), ["TR"], 5, datetime.now().replace(hour=0, minute=0))
    assert "kai" in run("/plan")
    hid = u.plan.gun_plani(datetime.now().date())["TR"][0]["hid"]
    asyncio.run(u._buton(f"pd:{hid}"))
    assert (u.klasor / "paylasildi" / "TR" / hid).exists()


def test_paylasim_hatirlatma(tmp_path, monkeypatch):
    import json
    u = _app(tmp_path, monkeypatch)
    giden = []

    async def video(yol, aciklama, kid, butonlar=None):
        giden.append(("video", aciklama, butonlar))

    async def html(metin, butonlar=None):
        giden.append(("html", metin, butonlar))

    u.bot.video_gonder, u.bot.html = video, html
    k = u.klasor / "hazir" / "TR" / "20261119_100000_kai_TR"
    k.mkdir(parents=True)
    (k / "a.mp4").write_bytes(b"x")
    (k / "aciklama.json").write_text(json.dumps({"instagram": "Kai <3 #gta6", "tiktok": "t", "youtube_baslik": "y #shorts",
                                                 "youtube_aciklama": "d"}))
    ok = asyncio.run(u._paylasim_hatirlat("TR", {"hid": k.name, "saat": "14:37"}))
    assert ok and giden[0][0] == "video" and "tt:" in giden[0][2][0][0]["callback_data"]
    assert "pd:" in giden[0][2][1][0]["callback_data"]
    assert "<code>Kai &lt;3 #gta6</code>" in giden[1][1] and "YouTube" in giden[1][1]


def test_sinir(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    assert u._ust_sinir() == 8 and u._sinir() == 6      # az yayınla başlar
    assert "30" in run("/sinir 30") and u._ust_sinir() == 30 and u._sinir() == 6
    assert "1 ile 100" in run("/sinir 500")
    assert "Sayı" in run("/sinir çok")
    assert "30" in run("/sinir")
    assert "4" in run("/sinir 4") and u._sinir() == 4


def test_kolay_komutlar_ve_dil_yonlendirme(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    out = run("/twitch kaicenat jynxzi")
    assert out.count("eklendi") == 2 and {"kaicenat", "jynxzi"} <= set(u._liste("twitch"))
    assert "eklendi" in run("/kick adinross") and "adinross" in u._liste("kick")
    assert "Örnek" in run("/youtube")
    assert [h["ad"] for h in u._hedef_hesaplar("tr")] == ["TR"]
    assert [h["ad"] for h in u._hedef_hesaplar("en")] == ["EN"]
    assert [h["ad"] for h in u._hedef_hesaplar("es")] == ["EN"]   # yabancı: İngilizce hesaba, İngilizceye çevrilerek
    asyncio.run(u._buton("hs:EN"))
    assert [h["ad"] for h in u._hedef_hesaplar("en")] == ["TR"]   # tek hesap açıksa her şey ona


def test_dil_kotasi(tmp_path, monkeypatch):
    from klipci.kesif import Kanal
    u = _app(tmp_path, monkeypatch)
    bulunan = [(Kanal("twitch", f"en{i}", dil="en"), 50000 - i) for i in range(10)] + \
              [(Kanal("twitch", "tr_buyuk", dil="tr"), 4000), (Kanal("twitch", "tr_kucuk", dil="tr"), 100)]

    async def tara(adet):
        return bulunan
    u._tara = tara
    sira = [k.ad for k, _ in asyncio.run(u._adaylar_oto(20))]
    assert sira[:2] == ["tr_buyuk", "tr_kucuk"] and "en0" in sira


def test_meme_uret(tmp_path, monkeypatch):
    import shutil
    import subprocess
    u = _app(tmp_path, monkeypatch)
    (u.klasor / "ham").mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi",
                    "-i", "sine", "-t", "4", "-c:v", "libx264", "-c:a", "aac", str(u.klasor / "ham" / "a.mp4")],
                   check=True)
    gonderilen = []

    async def gonder(k):
        gonderilen.append(k)
        return True
    u._gonder = gonder
    n = asyncio.run(u.meme_uret(1))
    assert n == 2 and len(gonderilen) == 2   # TR + EN
    assert all(list(k.glob("*.mp4")) and (k / "aciklama.json").exists() for k in gonderilen)
    assert "#gta6 #meme" in (gonderilen[0] / "aciklama.json").read_text()
    shutil.rmtree(u.klasor / "ham")
    assert asyncio.run(u.meme_uret(1)) == 0


def test_dil_filtresi(tmp_path, monkeypatch):
    from klipci.kesif import Kanal
    u = _app(tmp_path, monkeypatch)
    bulunan = [(Kanal("kick", "coringa", dil="pt"), 40000), (Kanal("kick", "xqc", dil="en"), 17000),
               (Kanal("kick", "tepki", dil="tr"), 6500), (Kanal("youtube", "abc", dil=""), 9000),
               (Kanal("kick", "3mr", dil="ar"), 30000)]

    async def tara(adet):
        return bulunan
    u._tara = tara
    # Arapça hiç alınmaz; diğer diller alınır (İngilizce hesaba, İngilizceye çevrilerek)
    assert sorted(k.ad for k, _ in asyncio.run(u._adaylar_oto(20))) == ["abc", "coringa", "tepki", "xqc"]
    u._yabanciya_ekle("kick:coringa")
    assert "coringa" not in [k.ad for k, _ in asyncio.run(u._adaylar_oto(20))]


def test_sayfa_ayarlari(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    h = u._hesaplar()[0]
    assert u._sayfa(h)["ust"] == "GTA 6'NIN EN İYİ ANLARI" and not u._sayfa(h)["profil"]
    assert "Sayfa adı" in run("/ad GTA 6 Anları")
    assert "Üst başlık" in run("/ustyazi en GTA 6 CLIPS THAT MADE MY DAY")
    tr, en = u._hesaplar()
    assert u._sayfa(tr)["ad"] == "GTA 6 Anları" and u._sayfa(en)["ust"] == "GTA 6 CLIPS THAT MADE MY DAY"
    assert "kaydedildi" in asyncio.run(u._profil_kaydet(b"\xff\xd8jpeg"))
    assert u._sayfa(tr)["profil"]


def test_klip_suresi(tmp_path, monkeypatch):
    from klipci.spike import Spike
    u = _app(tmp_path, monkeypatch)
    s = Spike(zaman=1000.0, tetik=1010.0, puan=80, taban=10)
    bas, bit = u._klip_araligi(s)
    assert bas == 1000 - 18 and bit == 1010 + 8      # sabit süre yok: olay + ilk tepki
    u.cfg["klip"] = {"once_sn": 22, "hedef_sure_sn": 50}   # eski ayar dosyası
    bas, bit = u._klip_araligi(s)
    assert bit - bas == 36


def test_info(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    m = asyncio.run(u._komut("/info"))
    for k in ("/durum", "/twitch", "/kick", "/youtube", "/guncelle", "/isim", "/gunluk", "/info"):
        assert k in m
    assert len(m) < 4000   # Telegram mesaj sınırı


def test_ayni_klip_iki_kez_gitmez(tmp_path, monkeypatch):
    import json
    u = _app(tmp_path, monkeypatch)
    u.bot.chat_id = "42"
    giden = []

    async def video(yol, aciklama, kid, butonlar=None):
        await asyncio.sleep(0.05)
        giden.append(kid)
    u.bot.video_gonder = video
    k = u.klasor / "bekleyen" / "20261120_120000_kai_EN"
    k.mkdir(parents=True)
    (k / "a.mp4").write_bytes(b"x")
    (k / "bilgi.json").write_text(json.dumps({"puan": 5}))

    async def iki_kez():
        await asyncio.gather(u._gonder(k), u._gonder(k))
    asyncio.run(iki_kez())
    asyncio.run(u._gonder(k))
    assert giden == ["20261120_120000_kai_EN"]


def test_ad_anahtar():
    from klipci.kesif import Kanal
    from klipci.uygulama import _ad_anahtar
    assert _ad_anahtar(Kanal("kick", "xqc", "xQc")) == _ad_anahtar(Kanal("twitch", "xqc"))


def test_sira(tmp_path, monkeypatch):
    from klipci.kesif import Kanal
    from klipci.uygulama import Is
    u = _app(tmp_path, monkeypatch)
    assert "hazırlanan klip yok" in asyncio.run(u._komut("/sira"))
    k = Kanal("twitch", "kaicenat", "KaiCenat")
    u._asama("t1", "⏳ sırada", k)
    m = asyncio.run(u._komut("/sira"))
    assert "KaiCenat (twitch) — ⏳ sırada" in m
    u._asama("t1", None)
    assert "yok" in asyncio.run(u._komut("/sira"))
    i = Is(k, None, tmp_path / "x.mp4", 1.0, 50.0, [], True, 22.0, "t9")
    assert i.an == 22.0 and i.takip == "t9"


def test_kalite_suzgeci(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    assert "yapay zekâ" in u._kalite_eler(9.0, 2)
    assert u._kalite_eler(6.5, None) != "" and u._kalite_eler(7.4, None) == ""   # varsayılan en az 7
    assert "8" in run("/kalite 8") and u._kalite_eler(7.4, None) != ""
    assert "1 ile 10" in run("/kalite 50")
    assert "8" in run("/kalite")


def test_kalite_puani():
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    komik = [(20 + i * 0.3, f"u{i}", "KEKW" if i % 4 else "clip it") for i in range(40)]
    s = Spike(0, 0, 80, 10)
    iyi = Is(kesif.Kanal("twitch", "x"), s, None, 0, 30, komik, True, 20.0, "x")
    p, neden = Uygulama.kalite_puani(iyi, 12.0, 2.8, False, 0.0, True)
    assert p >= 7.5 and "gül" in neden
    sakin = Is(kesif.Kanal("twitch", "x"), s, None, 0, 30, [(20 + i, "u", "selam") for i in range(20)], True,
               20.0, "x")
    assert Uygulama.kalite_puani(sakin, 3.0, 1.0, False, 0.0, True)[0] < 4


def test_durum_kanal_listesi(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    m = asyncio.run(u._komut("/durum"))
    assert "{kanal}" not in m and "şu an açık yayın yok" in m


def test_gecikme_klibi_kaydirir(tmp_path, monkeypatch):
    from klipci import kesif
    from klipci.spike import Spike
    u = _app(tmp_path, monkeypatch)
    s = Spike(zaman=1000.0, tetik=1010.0, puan=80, taban=10)
    assert u._gecikme(kesif.Kanal("kick", "x")) == 10
    bas, bit = u._klip_araligi(s, 10)
    assert bas == 1000 - 18 + 10 and bit == 1010 + 8 + 10


def test_bildirimler_varsayilan_kapali(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    giden = []

    async def yakala(m, **k):
        giden.append(m)
    u.bot.mesaj = yakala
    asyncio.run(u._bildir("▶ açıldı"))
    assert giden == []
    assert "açıldı" in asyncio.run(u._komut("/bildirim ac"))
    asyncio.run(u._bildir("▶ açıldı"))
    assert giden == ["▶ açıldı"]
    assert "kapandı" in asyncio.run(u._komut("/bildirim kapat"))



def test_hemen_paylas_begendim_ve_ozet(tmp_path, monkeypatch):
    import json
    from datetime import datetime
    u = _app(tmp_path, monkeypatch)
    giden = []

    async def video(yol, aciklama, kid, butonlar=None):
        giden.append(aciklama)

    async def html(metin, butonlar=None):
        pass
    u.bot.video_gonder, u.bot.html = video, html
    kid = "20261121_100000_kai_TR"
    k = u.klasor / "bekleyen" / kid
    k.mkdir(parents=True)
    (k / "a.mp4").write_bytes(b"x")
    (k / "aciklama.json").write_text(json.dumps({"instagram": "x", "tiktok": "t"}))
    cevap, _, klavye = asyncio.run(u._buton(f"bg:{kid}"))
    assert "Not aldım" in cevap and klavye[0][0]["callback_data"].startswith("hp:")
    async def hp():
        c = await u._buton(f"hp:{kid}")
        await asyncio.gather(*list(u._arka))   # arka plandaki yükleme bitsin
        return c
    cevap, _, _ = asyncio.run(hp())
    assert "Paylaşılıyor" in cevap and giden and (u.klasor / "hazir" / "TR" / kid).exists()
    asyncio.run(u._buton(f"tt:{kid}"))
    ozet = u._paylasim_ozeti(datetime.now().date(), "Bugün")
    assert "kai [TR]" in ozet and "🎵✅" in ozet
    assert u._aralik() == 5 and u._gunluk() == 10      # sabit saat düzeni: günde 10
    assert "BotFather" in asyncio.run(u._komut("/ikinci_bot"))



def test_once_sira_sonra_hemen_paylas(tmp_path, monkeypatch):
    import json
    u = _app(tmp_path, monkeypatch)

    async def video(*a, **k):
        pass

    async def html(*a, **k):
        pass
    u.bot.video_gonder, u.bot.html = video, html
    kid = "20261121_110000_kai_EN"
    k = u.klasor / "bekleyen" / kid
    k.mkdir(parents=True)
    (k / "a.mp4").write_bytes(b"x")
    (k / "aciklama.json").write_text(json.dumps({"instagram": "x"}))
    assert "Sıraya eklendi" in asyncio.run(u._onay(kid))        # önce ✅ sıraya
    async def hp():
        c = await u._buton(f"hp:{kid}")              # sonra 📤 hemen paylaş: bulmalı
        await asyncio.gather(*list(u._arka))
        return c
    cevap, _, _ = asyncio.run(hp())
    assert "Paylaşılıyor" in cevap
    try:
        asyncio.run(u._onay("20261121_000000_yok_EN"))
        assert False
    except RuntimeError as e:
        assert "artık yok" in str(e)


def test_meta_engellenince_bekler(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    cagri = []
    monkeypatch.setattr(u, "_ig_paylas", lambda h, *a: (cagri.append("ig"), {"instagram": "HATA: 400: API access blocked."})[1])
    monkeypatch.setattr(u, "_fb_paylas", lambda h, *a: {"facebook": "HATA: 400: API access blocked."} if h.get("facebook_token") else {})
    monkeypatch.setattr(u, "_yt_paylas", lambda h, *a: {"youtube": "https://youtube.com/shorts/x"})
    s = u._otomatik_paylas("EN", tmp_path / "a.mp4", {})
    assert "engelledi" in s["instagram"] and s["youtube"].startswith("https")
    assert u._durum_oku()["meta_engel"] > 0
    monkeypatch.setattr(u, "_ig_paylas", lambda h, *a: (cagri.append("ig2"), {"instagram": "x"} if h.get("instagram_token") else {})[1])
    s2 = u._otomatik_paylas("EN", tmp_path / "a.mp4", {})
    assert "instagram" not in s2 and s2["youtube"].startswith("https")   # 12 saat Meta denenmez, YouTube devam
    assert "sıfırlandı" in asyncio.run(u._komut("/meta_tekrar"))


def test_paylasilamayan_tekrar_denenir_ve_anlik(tmp_path, monkeypatch):
    import json
    u = _app(tmp_path, monkeypatch)
    kid = "20261122_200000_kai_EN"
    k = u.klasor / "hazir" / "EN" / kid
    k.mkdir(parents=True)
    (k / "a.mp4").write_bytes(b"x")
    (k / "aciklama.json").write_text(json.dumps({"instagram": "x"}))
    u._tekrar_ekle(kid, "EN", "instagram")
    giden = []

    async def mesaj(m, **kw):
        giden.append(m)
    u.bot.mesaj = mesaj
    monkeypatch.setattr(u, "_ig_paylas", lambda h, hs, mp4, pm: {"instagram": "HATA: 400: API access blocked."})
    assert asyncio.run(u._tekrar_dene()) == 0 and u._durum_oku()["tekrar"][0]["deneme"] == 1
    assert asyncio.run(u._tekrar_dene()) == 0          # Meta engelli: denenmez, bekler
    d = u._durum_oku(); d.pop("meta_engel"); u._durum_yaz(d)
    monkeypatch.setattr(u, "_ig_paylas", lambda h, hs, mp4, pm: {"instagram": "https://instagram.com/reel/x"})
    assert asyncio.run(u._tekrar_dene()) == 1 and not u._durum_oku()["tekrar"]
    assert "♻️" in giden[-1]
    # anlık paylaşım: 8.5+ hemen, 45 dk içinde ikincisi sıraya
    cagri = []

    async def hp(h):
        cagri.append(h)
    u._hemen_paylas = hp
    u.cfg["sabit_saatler"] = False     # anında paylaşım sadece sabit saat düzeni kapalıyken

    async def calis():
        a = u._anlik_paylas_mi("x1_EN", "EN", 9.1)
        b = u._anlik_paylas_mi("x2_EN", "EN", 9.3)
        c = u._anlik_paylas_mi("x3_TR", "TR", 7.9)
        await asyncio.gather(*list(u._arka))
        return a, b, c
    assert asyncio.run(calis()) == (True, False, False) and cagri == ["x1_EN"]


def test_anlik_paylasim_bekleyendeki_klibi_bulur(tmp_path, monkeypatch):
    """8.5+ klip onaysız 'bekleyen'deyken anında paylaşılınca dosya bulunmalı (önceden 'kayıp' sayılıyordu)."""
    import json
    u = _app(tmp_path, monkeypatch)
    kid = "20261122_210000_kai_EN"
    k = u.klasor / "bekleyen" / kid
    k.mkdir(parents=True)
    (k / "a.mp4").write_bytes(b"x")
    (k / "aciklama.json").write_text(json.dumps({"instagram": "x", "tiktok": "t"}))
    giden = []

    async def video(yol, aciklama, kid_, butonlar=None):
        giden.append(yol)

    async def html(*a, **kw):
        pass
    u.bot.video_gonder, u.bot.html = video, html
    assert "Paylaşılıyor" in asyncio.run(u._hemen_paylas(kid))
    assert giden and (u.klasor / "hazir" / "EN" / kid).exists()
    assert u.plan.bul(kid)[2]["durum"] == "gonderildi"



def test_gunluk_platform_siniri(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    cagri = []
    monkeypatch.setattr(u, "_ig_paylas", lambda h, *a: (cagri.append(bool(h.get("instagram_token"))),
                                                         {"instagram": "https://instagram.com/reel/x"}
                                                         if h.get("instagram_token") else {})[1])
    monkeypatch.setattr(u, "_fb_paylas", lambda h, *a: {})
    monkeypatch.setattr(u, "_yt_paylas", lambda h, *a: {})
    d = u._durum_oku()
    d["ig_token"] = {"EN": "T"}
    u._durum_yaz(d)
    sonuc = [u._otomatik_paylas("EN", tmp_path / "a.mp4", {}) for _ in range(7)]
    assert cagri == [True] * 6 + [False]                # günde en fazla 6 Instagram
    assert sonuc[6]["instagram"].startswith("SINIR")



def test_sabit_saatler_ve_platformlar(tmp_path, monkeypatch):
    from datetime import date, datetime
    u = _app(tmp_path, monkeypatch)
    sabit = u._sabit_saatler()
    assert len(sabit["TR"]) == 10 and len(sabit["EN"]) == 10
    ig = sum("instagram" in pl for _, pl in sabit["TR"])
    yt = sum("youtube" in pl for _, pl in sabit["EN"])
    assert ig == 3 and yt == 2
    g = u.plan.plan_yap(date(2026, 11, 23), ["TR", "EN"], 10, datetime(2026, 11, 23, 0, 0), 5, True, sabit)
    assert [i["saat"] for i in g["TR"]][:3] == ["09:00", "11:00", "12:30"]
    assert g["TR"][2]["platformlar"] == ["instagram", "facebook"]
    assert "02:30" in [i["saat"] for i in g["EN"]]
    # bu saatte sadece Facebook: Instagram'a gitmemeli
    cagri = []
    monkeypatch.setattr(u, "_ig_paylas", lambda h, *a: (cagri.append("ig"), {})[1] if h.get("instagram_token") else {})
    monkeypatch.setattr(u, "_fb_paylas", lambda h, *a: {})
    monkeypatch.setattr(u, "_yt_paylas", lambda h, *a: {})
    d = u._durum_oku(); d["ig_token"] = {"TR": "T"}; u._durum_yaz(d)
    u._otomatik_paylas("TR", tmp_path / "a.mp4", {}, ["facebook"])
    assert cagri == []
    assert "TR" in asyncio.run(u._komut("/saatler"))


def test_bayildim_ogrenir_ve_one_alir(tmp_path, monkeypatch):
    import json
    u = _app(tmp_path, monkeypatch)
    for i, (y, puan) in enumerate((("kai", 7.2), ("xqc", 8.4))):
        kid = f"20261123_10000{i}_{y}_EN"
        k = u.klasor / "bekleyen" / kid
        k.mkdir(parents=True)
        (k / "a.mp4").write_bytes(b"x")
        (k / "bilgi.json").write_text(json.dumps({"puan": puan, "surum": "t", "sure": 30}))
        u.ogrenci.puanla(kid, y, {"chat": 0.9, "tepki": 0.8, "ses": 0.7, "aksiyon": 0.2, "konusma": 0.3, "yuz": 0.0,
                                  "yz": 0.5})
    giden = []

    async def mesaj(m, **k):
        giden.append(m)
    u.bot.mesaj = mesaj
    assert u._en_iyi_aday("EN").endswith("xqc_EN")
    cevap, _, _ = asyncio.run(u._buton("by:20261123_100000_kai_EN"))
    assert "Anladım" in cevap and "coşkusu" in cevap
    assert u._en_iyi_aday("EN").endswith("kai_EN")          # 😍 bastığın ilk gider
    assert u._durum_oku()["favori"]["kai"] == 1
    baslik = u._baslik_metni({"puan": 9.0, "yayinci": "Kai", "platform": "twitch", "hesap": "EN",
                              "neden": "izleyiciler güldü"}, "x", "h")
    assert baslik.startswith("★★★★½") and "🔥 Çok iyi" in baslik


def test_sade_mod(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    b = {"puan": 7.4, "yayinci": "Kai", "platform": "twitch", "hesap": "EN", "neden": "izleyiciler güldü"}
    assert "Kai" in u._baslik_metni(b, "açıklama", "h")
    assert "Sade" in asyncio.run(u._komut("/sade"))
    assert u._baslik_metni(b, "açıklama", "h") == "★★★½☆  7.4/10"
    asyncio.run(u._komut("/detay"))
    assert "Kai" in u._baslik_metni(b, "açıklama", "h")


def test_part_serisi_numarasi(tmp_path, monkeypatch):
    import time
    u = _app(tmp_path, monkeypatch)
    pm = {"instagram": "“Abi bu ne”\nGünün anı\n\nPart 2 gelsin mi? 👇", "tiktok": "x", "youtube_baslik": "Abi | GTA 6",
          "youtube_aciklama": "y"}
    assert u._part_metni("EN", "20261128_100000_eray_EN", pm) == pm           # ilk klip: değişmez
    u.performans.kaydet("20261128_090000_eray_EN", "EN", "eray", {"youtube": "a"})
    u.performans.kaydet("20261128_080000_kai_EN", "EN", "kai", {"youtube": "b"})
    yeni = u._part_metni("EN", "20261128_100000_eray_EN", pm)
    assert yeni["instagram"].startswith("Part 2 🎬") and yeni["youtube_baslik"].startswith("Part 2:")
    assert "Part 3" in yeni["instagram"] and "Part 2 gelsin" not in yeni["instagram"]
    assert time.time()


def test_duello_oy_sayimi_ve_video(tmp_path):
    import subprocess
    from klipci.duello import duello_video, oy_say
    assert oy_say(["1", "1 😂", "ikinci", "2", "bence 1", "First!"]) == (3, 2)
    vs = []
    for i in range(2):
        v = tmp_path / f"k{i}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:d=8",
                        "-f", "lavfi", "-i", "sine=d=8", "-shortest", str(v)], check=True)
        vs.append(v)
    out = duello_video(vs[0], 4, vs[1], 4, tmp_path / "d.mp4", "tr", ("Eray", "Kai"), parca=4, son_sn=1.5)
    from klipci.kayit import sure_olc
    assert 9 <= sure_olc(out) <= 10.5


def test_izleyici_klip_ayiklama():
    from klipci.izleyici_klip import harici_puan, kick_ayikla, twitch_ayikla
    k = kick_ayikla({"clips": [{"id": "clip_1", "title": "LMAO", "clip_url": "https://clips.kick.com/a/playlist.m3u8",
                                "views": 900, "duration": 30, "channel": {"slug": "eray", "username": "Eray"},
                                "category": {"name": "Grand Theft Auto VI"}}, {"id": "x"}]})
    assert len(k) == 1 and k[0]["kanal_ad"] == "eray" and k[0]["izlenme"] == 900
    t = twitch_ayikla({"data": {"game": {"clips": {"edges": [{"node": {
        "slug": "Abc", "title": "t", "viewCount": 5000, "durationSeconds": 28, "language": "en",
        "broadcaster": {"login": "KaiCenat", "displayName": "Kai Cenat"}}}]}}}})
    assert t[0]["kanal_ad"] == "kaicenat" and t[0]["dil"] == "en"
    assert harici_puan(150, "twitch") == 7.2 and harici_puan(150000, "twitch") == 9.5
