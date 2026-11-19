from klipci.spike import SpikeDetector, mesaj_puani


def _besle(d, bas, bit, hiz, metin="hello"):
    """hiz: saniyede mesaj"""
    t = bas
    adim = 1.0 / hiz
    while t < bit:
        d.ekle(t, metin)
        t += adim


def test_sakin_chat_patlama_yok():
    d = SpikeDetector(isinma_sn=60)
    _besle(d, 0, 400, 2)
    assert all(d.kontrol(t) is None for t in range(60, 400, 2))


def test_patlama_algilanir_ve_zamani_dogru():
    d = SpikeDetector(isinma_sn=60)
    _besle(d, 0, 300, 2)
    _besle(d, 300, 315, 20, "LMAO")
    sonuc = None
    for t in range(290, 320):
        s = d.kontrol(t)
        if s:
            sonuc = s
            break
    assert sonuc is not None
    assert 300 <= sonuc.tetik <= 310
    assert "lmao" in sonuc.kelimeler
    assert sonuc.kat > 3


def test_bekleme_suresi():
    d = SpikeDetector(isinma_sn=60, bekleme_sn=120)
    _besle(d, 0, 300, 2)
    _besle(d, 300, 330, 20, "KEKW")
    spikes = [d.kontrol(t) for t in range(300, 330)]
    assert sum(1 for s in spikes if s) == 1


def test_kucuk_chat_alt_sinir():
    d = SpikeDetector(isinma_sn=60, en_az_mesaj=25)
    _besle(d, 0, 300, 0.1)
    _besle(d, 300, 310, 1)   # 10x ama sadece ~10 mesaj
    assert all(d.kontrol(t) is None for t in range(300, 312))


def test_isinma():
    d = SpikeDetector(isinma_sn=90)
    _besle(d, 0, 20, 30, "LOL")
    assert d.kontrol(19) is None


def test_mesaj_puani():
    assert mesaj_puani("LMAOOOO")[0] > 1
    assert mesaj_puani("clip that")[0] == 1.5 or mesaj_puani("clip that")[1] == "clip"
    assert mesaj_puani("merhaba")[0] == 1.0
