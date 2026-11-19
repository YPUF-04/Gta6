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
    (k / "bilgi.json").write_text(json.dumps({"puan": puan}))


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
