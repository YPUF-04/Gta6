from klipci.yuz import facecam_sec


def test_sabit_yuz_facecam_olur():
    w, h = 960, 540
    # sol altta sabit facecam yüzü + her karede farklı yerde oyun yüzü
    kutular = [[(60 + (i % 2), 380, 50, 50), (100 + i * 60, 100, 30, 30)] for i in range(12)]
    fc = facecam_sec(kutular, w, h)
    assert fc is not None
    x, y, fw, fh = fc
    assert x < 0.15 and y > 0.4 and 0 < fw <= 1 and 0 < fh <= 1
    assert x + fw <= 1.0001 and y + fh <= 1.0001


def test_yuz_yoksa_none():
    assert facecam_sec([[] for _ in range(10)], 960, 540) is None


def test_nadir_yuz_none():
    kutular = [[] for _ in range(10)]
    kutular[3] = [(100, 100, 60, 60)]
    assert facecam_sec(kutular, 960, 540) is None
