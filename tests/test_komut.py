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
    assert "/ekle" in run("/yardim")
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
    assert ok and giden[0][0] == "video" and "pd:" in giden[0][2][0][0]["callback_data"]
    assert "<code>Kai &lt;3 #gta6</code>" in giden[1][1] and "YouTube" in giden[1][1]
