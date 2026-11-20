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


def test_kes_eksik_kayit(tmp_path):
    import time
    from datetime import datetime
    from klipci.kayit import Kaydedici
    k = Kaydedici("x", tmp_path, "best", 9999)
    simdi = time.time()
    for t in (simdi - 400, simdi - 396, simdi - 8, simdi - 4, simdi):   # arada büyük boşluk
        (tmp_path / (datetime.fromtimestamp(t).strftime("%Y%m%d_%H%M%S") + ".ts")).write_bytes(b"x")
    assert k.kes(simdi - 200, simdi - 170, tmp_path / "o.ts") is None


def test_kes_uzun_parcali_yayin(tmp_path):
    """Kick gibi 8 sn'lik parçalarda kesinti sanılmamalı."""
    import subprocess
    import time
    from datetime import datetime
    from klipci.kayit import Kaydedici
    k = Kaydedici("x", tmp_path, "best", 9999)
    simdi = int(time.time())
    kaynak = tmp_path / "k.ts"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30", "-t", "8",
                    "-c:v", "libx264", "-f", "mpegts", str(kaynak)], check=True)
    for t in range(simdi - 64, simdi + 1, 8):
        (tmp_path / (datetime.fromtimestamp(t).strftime("%Y%m%d_%H%M%S") + ".ts")).write_bytes(kaynak.read_bytes())
    kaynak.unlink()
    assert k.kes(simdi - 50, simdi - 20, tmp_path / "out" / "o.ts") is not None


def test_baglanti_kopunca_yanlis_alarm_yok():
    d = SpikeDetector(isinma_sn=60)
    _besle(d, 0, 300, 3)
    _besle(d, 340, 420, 3)          # 40 sn sessizlik (koptu) sonra normal chat
    assert all(d.kontrol(t) is None for t in range(340, 420))


def test_kes_duzensiz_kick_parcalari(tmp_path):
    import subprocess
    import time
    from datetime import datetime
    from klipci.kayit import Kaydedici
    k = Kaydedici("x", tmp_path, "best", 9999)
    simdi = int(time.time())
    kaynak = tmp_path / "k.ts"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30", "-t", "4",
                    "-c:v", "libx264", "-f", "mpegts", str(kaynak)], check=True)
    for t in [simdi - 40, simdi - 36, simdi - 32, simdi - 24, simdi - 20, simdi - 16, simdi - 8, simdi - 4, simdi]:
        (tmp_path / (datetime.fromtimestamp(t).strftime("%Y%m%d_%H%M%S") + ".ts")).write_bytes(kaynak.read_bytes())
    kaynak.unlink()
    assert k.kes(simdi - 38, simdi - 10, tmp_path / "out" / "o.ts") is not None


def test_kilitli_tampon_yeni_klasor(tmp_path, monkeypatch):
    import pathlib
    from klipci import kayit
    k = kayit.Kaydedici("x", tmp_path / "twitch_zarbex", "best", 9999)
    (tmp_path / "twitch_zarbex").mkdir()
    (tmp_path / "twitch_zarbex" / "20261120_114325.ts").write_bytes(b"x")

    def kilitli(self, missing_ok=False):
        raise PermissionError("WinError 32")
    monkeypatch.setattr(pathlib.Path, "unlink", kilitli)

    class Sahte:
        stdout = type("S", (), {"close": lambda self: None})()

        def poll(self):
            return None
    monkeypatch.setattr(kayit.subprocess, "Popen", lambda *a, **kw: Sahte())
    k.baslat()   # hata vermemeli
    assert k.klasor.name.startswith("twitch_zarbex_") and k.klasor.exists()


def test_yeniden_baslatinca_kayit_silinmez(tmp_path, monkeypatch):
    from klipci import kayit

    class Sahte:
        stdout = type("S", (), {"close": lambda self: None})()

        def poll(self):
            return 0
    monkeypatch.setattr(kayit.subprocess, "Popen", lambda *a, **kw: Sahte())
    k = kayit.Kaydedici("x", tmp_path / "twitch_kai", "best", 9999)
    k.baslat()
    (k.klasor / "20261120_120000.ts").write_bytes(b"x")
    assert not k.calisiyor_mu()
    k.yeniden_baslat()
    assert (k.klasor / "20261120_120000.ts").exists()


def test_reklam_boslugunda_klip_kisalir(tmp_path):
    """Twitch reklamı gibi 90 sn boşluk: patlama anını içeren kesintisiz kısımdan klip yapılmalı."""
    import subprocess
    import time
    from datetime import datetime
    from klipci.kayit import Kaydedici
    k = Kaydedici("x", tmp_path, "best", 9999)
    simdi = int(time.time())
    kaynak = tmp_path / "k.ts"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30", "-f", "lavfi",
                    "-i", "sine", "-t", "4", "-c:v", "libx264", "-c:a", "aac", "-f", "mpegts", str(kaynak)], check=True)
    zamanlar = list(range(simdi - 200, simdi - 140, 4)) + list(range(simdi - 52, simdi + 1, 4))   # arada 88 sn reklam
    for t in zamanlar:
        (tmp_path / (datetime.fromtimestamp(t).strftime("%Y%m%d_%H%M%S") + ".ts")).write_bytes(kaynak.read_bytes())
    kaynak.unlink()
    sonuc = k.kes(simdi - 75, simdi - 15, tmp_path / "out" / "o.ts", odak=simdi - 30)
    assert sonuc is not None
    _, _, bas, bit = sonuc
    assert bas >= simdi - 53 and bit - bas >= 20
    # patlama tam reklamın ortasındaysa: klip yok, nedeni yazılı
    assert k.kes(simdi - 130, simdi - 70, tmp_path / "out" / "p.ts", odak=simdi - 100) is None
    assert "reklam" in k.son_neden
