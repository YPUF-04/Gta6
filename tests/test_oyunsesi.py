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
    komik = Is(k, s, tmp_path / "a.ts", 0, 30, [(20.0 + i * 0.2, f"u{i}", ("LMAOOO", "KEKW")[i % 2]) for i in range(10)],
               True, 20.0, "x")
    assert Uygulama._bos_an_mi(komik, 2.0, []) == ""
    biraz = Is(k, s, tmp_path / "a.ts", 0, 30, [(20.0 + i * 0.2, f"u{i}", ("LMAO", "KEKW", "ok", "yo", "hi")[i % 5])
                                                for i in range(30)], True, 20.0, "x")
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
    chat = [(20.0 + i * 0.2, f"u{i}", ("LMAOOO", "KEKW", "ok")[i % 3]) for i in range(12)]
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
    # kayıt yayıncı konuşurken bitiyor (cümle 27-34, kayıt 30 sn): yarım cümle yerine cümleden önce bitsin
    is_.sure = 30
    chat3 = [(9 + i * 0.25, "a", "KEKW") for i in range(24)] + [(15 + i * 0.5, f"k{i}", "KEKW") for i in range(30)]
    is_.chat = chat3
    _, son3 = Uygulama._akilli_aralik(is_, [(27.0, 34.0, "ve sonra adam dedi ki")])
    assert son3 <= 27.0
    # kanca: olaydan önce kimse konuşmuyor (yayıncı sadece sonra konuşuyor) → giriş 6 değil ~4 sn
    bas4, _ = Uygulama._akilli_aralik(is_, [(11.0, 14.0, "abi noluyor")])
    assert abs(bas4 - 6.0) < 0.01


def test_aksiyon_puani_yukseltir():
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    chat = [(20 + i * 0.3, f"u{i}", "KEKW" if i % 2 else "ok") for i in range(30)]
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
    assert bas == 6.0 and 44 <= son - bas <= 46


def test_spam_ve_hep_gulen_chat_puani_sisirmez(tmp_path):
    from klipci import kesif
    from klipci.spike import Spike
    from klipci.uygulama import Is, Uygulama
    k, s = kesif.Kanal("twitch", "x"), Spike(0, 0, 50, 10)
    gercek = [(30 + i * 0.3, f"u{i}", "KEKW") for i in range(30)]                          # 30 farklı kişi güldü
    spam = [(30 + i * 0.3, "tek", "KEKW") for i in range(25)] + [(30 + i, f"u{i}", "ok") for i in range(5)]
    hep = [(5 + i * 0.5, f"a{i % 20}", "KEKW" if i % 2 else "lol") for i in range(40)] + \
          [(30 + i * 0.5, f"b{i}", "KEKW" if i % 2 else "nice") for i in range(20)]       # zaten hep gülen chat
    oran = lambda c: Uygulama._gulme_orani(Is(k, s, None, 0, 45, c, True, 30.0, "t"))
    assert oran(gercek) > 0.9
    assert oran(spam) < 0.6           # tek kişinin spam'i "herkes gülüyor" sayılmaz
    assert oran(hep) < 0.4            # chat'in normali zaten gülmekse bu an özel sayılmaz


def test_ses_zirvesi_olayin_anini_bulur(tmp_path):
    import subprocess
    from klipci.oyunsesi import ses_zirvesi
    v = tmp_path / "v.mp4"
    # 20 sn sessiz-ish ses, 12. saniyede 1 sn yüksek patlama
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=20:a=0.02", "-f", "lavfi",
                    "-i", "sine=f=300:d=1", "-filter_complex",
                    "[1:a]volume=8,adelay=12000|12000[p];[0:a][p]amix=inputs=2:duration=first[a]", "-map", "[a]",
                    str(v)], check=True)
    t, db = ses_zirvesi(v, 0, 20, an=16.0)      # chat 16. sn'de tepki verdi
    assert 11.5 <= t <= 13.0 and db > 7


def test_kapkara_son_kesilir():
    from klipci.oyunsesi import karanliktan_kirp
    # 0-10 sn oyun, 11. sn'den sonra yükleme ekranı (kapkara)
    k = [False] * 11 + [True] * 11
    bas, son = karanliktan_kirp(k, 0.0, 22.0, 6.0)
    assert bas == 0.0 and son == 11.0
    # başta sahne geçişi
    k2 = [True] * 4 + [False] * 20
    bas2, son2 = karanliktan_kirp(k2, 0.0, 24.0, 10.0)
    assert bas2 == 4.0 and son2 == 24.0


def test_karanlik_anlar_siyah_videoyu_bulur(tmp_path):
    import subprocess
    from klipci.oyunsesi import karanlik_anlar
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:d=3",
                    "-f", "lavfi", "-i", "color=black:size=320x568:rate=30:d=3",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[o]", "-map", "[o]", str(v)], check=True)
    k = karanlik_anlar(v, 0, 6)
    assert k[:2] == [False, False] and all(k[4:])


def test_ciplak_kelime_yedegi(monkeypatch):
    from klipci import ciplak
    monkeypatch.setattr(ciplak, "_model", lambda: None)
    chat = [(1.0, f"u{i}", "omg boobs lol") for i in range(3)]
    assert ciplak.ciplak_mi(None, 0, 10, chat, [])[0]
    assert not ciplak.ciplak_mi(None, 0, 10, [(1.0, "a", "KEKW")], [])[0]


def test_ciplak_model_temiz_videoda_bir_sey_bulmaz(tmp_path):
    import subprocess
    from klipci import ciplak
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:d=3", str(v)],
                   check=True)
    assert ciplak.ciplak_mi(v, 0, 3, [], []) == (False, "")
