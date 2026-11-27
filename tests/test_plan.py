import json
from datetime import date, datetime

from klipci.plan import Planlayici, saatler_sec


def test_saatler_her_gun_farkli_ve_yayilmis():
    a = saatler_sec(5, date(2026, 11, 20))
    b = saatler_sec(5, date(2026, 11, 21))
    assert len(a) == 5 and a != b and a == sorted(a)
    assert a[0] < "13:00" and a[-1] >= "17:00"


def test_bugun_gecmis_saat_yok():
    s = saatler_sec(5, date(2026, 11, 20), datetime(2026, 11, 20, 18, 0))
    assert all(x >= "18:05" for x in s)


def _klip(kok, hesap, ad, puan):
    k = kok / "hazir" / hesap / ad
    k.mkdir(parents=True)
    (k / f"{ad}.mp4").write_bytes(b"x")
    (k / "bilgi.json").write_text(json.dumps({"puan": puan, "surum": "t", "sure": 30}))


def test_plan_en_iyileri_secer(tmp_path):
    for i, (y, p) in enumerate([("kai", 9), ("kai", 8.5), ("xqc", 7), ("n3on", 3), ("kai", 2), ("speed", 6)]):
        _klip(tmp_path, "TR", f"20261119_1{i}0000_{y}_TR", p)
    pl = Planlayici(tmp_path)
    g = pl.plan_yap(date(2026, 11, 20), ["TR"], 4)
    secilen = [i["hid"] for i in g["TR"]]
    assert len(secilen) == 4
    assert not any("n3on" in h or "_kai_TR" in h and "140000" in h for h in secilen)
    assert len(pl.stok("TR")) == 2
    # tekrar çağırınca aynı plan kalır
    assert [i["hid"] for i in pl.plan_yap(date(2026, 11, 20), ["TR"], 4)["TR"]] == secilen
    gelen = pl.zamani_gelenler(datetime(2026, 11, 20, 23, 59))
    assert len(gelen) == 4
    pl.paylasildi("TR", secilen[0])
    assert (tmp_path / "paylasildi" / "TR" / secilen[0]).exists()
    assert len(pl.zamani_gelenler(datetime(2026, 11, 20, 23, 59))) == 3


def test_tam_otomatik_en_iyiyi_secer(tmp_path, monkeypatch):
    import json
    from datetime import date, datetime
    from tests.test_komut import _app
    u = _app(tmp_path, monkeypatch)

    def klip(yer, ad, puan):
        k = (u.klasor / yer / ad) if yer == "bekleyen" else (u.klasor / "hazir" / "EN" / ad)
        k.mkdir(parents=True)
        (k / "a.mp4").write_bytes(b"x")
        (k / "bilgi.json").write_text(json.dumps({"puan": puan, "surum": "t", "sure": 30}))
    klip("bekleyen", "20261122_100000_kai_EN", 9.1)      # onaylanmamış ama çok iyi
    klip("hazir", "20261122_100100_xqc_EN", 8.0)         # senin ✅ bastığın (+0.5 = 8.5)
    klip("bekleyen", "20261122_100200_abc_EN", 6.0)      # 7'nin altı: asla
    assert u._en_iyi_aday("EN") == "20261122_100000_kai_EN"
    u._hazira_al("20261122_100000_kai_EN")
    assert (u.klasor / "hazir" / "EN" / "20261122_100000_kai_EN").exists()
    # saatler boş açılır, klip saati gelince seçilir
    g = u.plan.plan_yap(date(2026, 11, 22), ["EN"], 5, datetime(2026, 11, 22, 8, 0), 3, otomatik=True)
    assert len(g["EN"]) == 5 and all(it["hid"] == "" for it in g["EN"])
    u.plan.ata("2026-11-22", "EN", g["EN"][0]["saat"], "20261122_100000_kai_EN")
    assert u.plan.planli_mi("20261122_100000_kai_EN")
    assert u._en_iyi_aday("EN") == "20261122_100100_xqc_EN"   # planlanan tekrar seçilmez


def test_merge_simulasyonu_boss_ve_olaylar():
    from klipci.merge import BOSS, simule
    kareler, olaylar = simule(20, 3)
    assert len(kareler) == 20 * 30
    assert any(tur == "birles" for _, tur, _ in olaylar)
    assert kareler[-1][1] > 0                      # skor arttı
    assert all(0 <= sv <= BOSS for top, _ in kareler for *_x, sv, _y in top)


def test_sekme_buyume_egrisi():
    from klipci.sekme import simule
    _, olaylar = simule(50, 4)
    esik = {v: t for t, tur, v in olaylar if tur == "esik"}
    assert 4 < esik[10] < 14 and 14 < esik[100] < 24 and 25 < esik[1000] < 36
    assert any(tur == "tasti" for _, tur, _ in olaylar)


def test_sarkac_bloklar_yapisir():
    from klipci.sarkac import simule
    kareler, olaylar = simule(20, 1)
    assert kareler[-1][6] > 5 and sum(1 for _, tur, _ in olaylar if tur == "yapisti") == kareler[-1][6]


def test_en_guzel_secim_ayni_yayinciyi_art_arda_vermez(tmp_path, monkeypatch):
    """Bugün az önce kai gittiyse, kai'nin biraz daha yüksek puanlı klibi yerine başka yayıncının güzel klibi gider."""
    import json
    from datetime import datetime
    from tests.test_komut import _app
    u = _app(tmp_path, monkeypatch)
    for ad, puan in (("20261122_100000_kai_EN", 8.6), ("20261122_100100_xqc_EN", 8.2)):
        k = u.klasor / "bekleyen" / ad
        k.mkdir(parents=True)
        (k / "a.mp4").write_bytes(b"x")
        (k / "bilgi.json").write_text(json.dumps({"puan": puan, "surum": "t", "sure": 30}))
    assert u._en_iyi_aday("EN") == "20261122_100000_kai_EN"
    gun = datetime.now().date().isoformat()
    u.plan.ekle(datetime.now().date(), "EN", "20261122_090000_kai_EN", "09:00", "gonderildi")
    hid, neden = u._en_iyi_aday("EN", True)
    assert hid == "20261122_100100_xqc_EN" and gun


def test_eski_surum_ve_kisa_klip_secilmez(tmp_path, monkeypatch):
    import json
    from tests.test_komut import _app
    u = _app(tmp_path, monkeypatch)
    for ad, b in (("20261122_100000_eski_EN", {"puan": 9.5}),
                  ("20261122_100100_kisa_EN", {"puan": 9.4, "surum": "x", "sure": 13.9}),
                  ("20261122_100200_iyi_EN", {"puan": 8.0, "surum": "x", "sure": 30})):
        k = u.klasor / "bekleyen" / ad
        k.mkdir(parents=True)
        (k / "a.mp4").write_bytes(b"x")
        (k / "bilgi.json").write_text(json.dumps(b))
    assert u._en_iyi_aday("EN") == "20261122_100200_iyi_EN"


def test_trend_yayinci_puani_ve_etiketler(tmp_path):
    import httpx
    from klipci.trend import Trend

    def cevap(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "a"}}, {"id": {"videoId": "b"}}]})
        return httpx.Response(200, json={"items": [
            {"id": "a", "snippet": {"title": "Kai Cenat loses it in GTA 6 #gta6 #kaicenat", "channelTitle": "Clips",
                                    "description": "", "tags": []},
             "statistics": {"viewCount": "2500000"}, "contentDetails": {"duration": "PT34S"}},
            {"id": "b", "snippet": {"title": "cooking video", "channelTitle": "x", "description": ""},
             "statistics": {"viewCount": "9"}, "contentDetails": {"duration": "PT20S"}}]})
    t = Trend(tmp_path / "trend.json")
    assert t.eski_mi()
    n = t.guncelle("tok", sorgular=("GTA 6",), http=httpx.Client(transport=httpx.MockTransport(cevap)))
    assert n == 1 and not t.eski_mi()
    assert t.yayinci_puani("kaicenat", "Kai Cenat") == 1.0
    assert t.yayinci_puani("xqc") == 0.0
    assert "#gta6" in t.populer_etiketler()
    assert "34 sn" in t.ozet(["kaicenat"])
    assert Trend(tmp_path / "trend.json").videolar   # diske yazıldı
