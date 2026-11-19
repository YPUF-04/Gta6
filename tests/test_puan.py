from klipci.puan import Ogrenci, ozellik_cikar, taban_puan


def _oz(ses, chat):
    return {"chat": chat, "tepki": 0.5, "ses": ses, "aksiyon": 0.3, "konusma": 0.3, "yuz": 1.0, "yz": 0.5}


def test_taban_puan_aralik():
    assert 0 <= taban_puan(_oz(0, 0)) < taban_puan(_oz(1, 1)) <= 10


def test_ozellik_cikar():
    oz = ozellik_cikar(4.0, [(1, "a", "LMAO"), (2, "b", "hello")], 30, {"ses": 0.8}, 0.4, 40, True, 7)
    assert oz["chat"] == 0.5 and oz["tepki"] == 0.75 and oz["yuz"] == 1.0 and oz["yz"] == 0.7


def test_ogrenme_yuksek_sesi_sevene_gore(tmp_path):
    o = Ogrenci(tmp_path / "p.jsonl")
    for i in range(12):
        ses = 1.0 if i % 2 else 0.0
        o.puanla(f"k{i}", "kai" if i % 2 else "xqc", _oz(ses, 0.5))
        o.karar(f"k{i}", "onay" if ses else "sil")
    yuksek, neden = o.puanla("yeni1", "kai", _oz(1.0, 0.5))
    dusuk, _ = o.puanla("yeni2", "xqc", _oz(0.0, 0.5))
    assert yuksek > dusuk + 2
    assert "bağırma" in neden or "ses" in neden
    assert "kai" in o.ozet()
    # kalıcı
    o2 = Ogrenci(tmp_path / "p.jsonl")
    assert o2.w and len(o2.kararlilar()) == 12
    assert o2.sira("yeni1")[0] >= 1
