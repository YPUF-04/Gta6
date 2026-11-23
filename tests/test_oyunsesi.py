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
    assert "işareti yok" in Uygulama._bos_an_mi(sakin, 2.0, [])
    komik = Is(k, s, tmp_path / "a.ts", 0, 30, [(20.0, "a", "LMAOOO"), (21.0, "b", "KEKW")] * 5, True, 20.0, "x")
    assert Uygulama._bos_an_mi(komik, 2.0, []) == ""
    biraz = Is(k, s, tmp_path / "a.ts", 0, 30, [(20.0, "a", "LMAO"), (20.5, "b", "KEKW"), (21.0, "c", "ok"),
                                                (21.5, "d", "yo"), (22.0, "e", "hi")] * 3, True, 20.0, "x")
    assert "ara sahne" in Uygulama._bos_an_mi(biraz, 9.0, [(t, True) for t in range(10)])


def test_hareketsiz_ekran(tmp_path):
    import subprocess
    from klipci.oyunsesi import hareketsiz_oran
    durgun, hareketli = tmp_path / "d.mp4", tmp_path / "h.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=gray:s=320x180:d=8", str(durgun)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=8", str(hareketli)], check=True)
    assert hareketsiz_oran(durgun, 0, 8) > 0.9
    assert hareketsiz_oran(hareketli, 0, 8) < 0.2


def test_oyun_karakteri_ani(tmp_path):
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    chat = [(20.0, "a", "LMAOOO"), (21.0, "b", "KEKW"), (21.5, "c", "ok")] * 4
    is_ = Is(kesif.Kanal("kick", "x"), Spike(0, 0, 1, 1), tmp_path / "a.ts", 0, 30, chat, True, 20.0, "x")
    npc = [(t / 2, 12 <= t / 2 <= 24) for t in range(60)]   # patlama anında oyunda biri konuşuyor
    assert Uygulama._oyun_ani_mi(is_, 7.0, npc)
    assert not Uygulama._oyun_ani_mi(is_, 7.0, [(t / 2, False) for t in range(60)])
    # yayıncı sakin (yüz 1x) ama karakter anı: geçer
    assert Uygulama._bos_an_mi(is_, 7.0, npc, 1.0, oyun_ani=True) == ""


def test_akilli_aralik_bos_kuyrugu_keser(tmp_path):
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    # patlama 10. sn; chat 9-15 arası güldü, sonra sıradan mesajlar (soygun devam ediyor ama komik bir şey yok)
    chat = [(9 + i * 0.25, "a", "KEKW") for i in range(24)] + [(16 + i, "b", "devam abi") for i in range(14)]
    is_ = Is(kesif.Kanal("kick", "barisg"), Spike(0, 0, 1, 1), tmp_path / "a.ts", 0, 30, chat, False, 10.0, "x")
    bas, son = Uygulama._akilli_aralik(is_, [])
    assert bas == 4.0 and 17 <= son <= 22          # olaydan ~6 sn önce başlar, boş kuyruk gitti
    # yayıncı tam bitişte konuşuyorsa cümlesini bitirsin
    bas2, son2 = Uygulama._akilli_aralik(is_, [(18.0, 23.0, "abi bu ne ya")])
    assert abs(son2 - 23.3) < 0.01


def test_aksiyon_puani_yukseltir():
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    chat = [(20 + i * 0.3, "u", "KEKW" if i % 2 else "ok") for i in range(30)]
    is_ = Is(kesif.Kanal("twitch", "x"), Spike(0, 0, 50, 10), None, 0, 30, chat, True, 20.0, "x")
    sakin, _ = Uygulama.kalite_puani(is_, 5.0, 1.0, False, 0.0, True, aksiyon=1.0)
    kaza, neden = Uygulama.kalite_puani(is_, 5.0, 1.0, False, 0.0, True, aksiyon=3.0)
    assert kaza - sakin >= 1.9 and "aksiyon" in neden


def test_ara_sahne_oyun_ani_sayilmaz(tmp_path):
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    is_ = Is(kesif.Kanal("kick", "maddyson"), Spike(0, 0, 1, 1), tmp_path / "a.ts", 0, 40, [], True, 20.0, "x")
    ara_sahne = [(t / 2, True) for t in range(80)]          # baştan sona oyun altyazısı = ara sahne/diyalog
    assert not Uygulama._oyun_ani_mi(is_, 8.0, ara_sahne)


def test_klip_en_fazla_60_sn(tmp_path):
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    chat = [(10 + i * 0.25, "a", "KEKW") for i in range(320)]     # chat 80 sn boyunca gülüyor
    is_ = Is(kesif.Kanal("kick", "x"), Spike(0, 0, 1, 1), tmp_path / "a.ts", 0, 90, chat, False, 12.0, "x")
    bas, son = Uygulama._akilli_aralik(is_, [])
    assert bas == 6.0 and 55 <= son - bas <= 60.5
