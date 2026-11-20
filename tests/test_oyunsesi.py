import numpy as np

from klipci.oyunsesi import BANT_Y, bant_yazi_var_mi, oyun_konusmasi_mi


def test_oyun_altyazisi_bulunur():
    import cv2
    kare = np.full((720, 1280), 70, np.uint8)
    assert not bant_yazi_var_mi(kare)
    cv2.putText(kare, "Ey man, c'mon. I need y'all.", (430, BANT_Y[0] + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 235, 2)
    assert bant_yazi_var_mi(kare)


def test_parlak_gokyuzu_yazi_sanilmaz():
    kare = np.full((720, 1280), 230, np.uint8)
    assert not bant_yazi_var_mi(kare)


def test_oyun_konusmasi_mi():
    anlar = [(t / 2, 4 <= t / 2 <= 8) for t in range(30)]
    assert oyun_konusmasi_mi(4.5, 7.5, anlar)
    assert not oyun_konusmasi_mi(10, 13, anlar)
    assert not oyun_konusmasi_mi(1, 3, [])


def test_bos_an(tmp_path, monkeypatch):
    from klipci.spike import Spike
    from klipci.uygulama import Is
    from klipci import kesif
    k = kesif.Kanal("twitch", "kai")
    s = Spike(zaman=0, tetik=0, puan=1, taban=1)
    sakin = Is(k, s, tmp_path / "a.ts", 0, 30, [(20.0, "a", "nice"), (21.0, "b", "hello")] * 5, True, 20.0, "x")
    from klipci.uygulama import Uygulama
    assert "tepki" in Uygulama._bos_an_mi(sakin, 2.0, [])
    komik = Is(k, s, tmp_path / "a.ts", 0, 30, [(20.0, "a", "LMAOOO"), (21.0, "b", "KEKW")] * 5, True, 20.0, "x")
    assert Uygulama._bos_an_mi(komik, 2.0, []) == ""
    assert "ara sahne" in Uygulama._bos_an_mi(sakin, 9.0, [(t, True) for t in range(10)])
