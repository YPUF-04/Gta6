import io
import zipfile

from klipci import guncelle as g


def test_guncelle_korunanlara_dokunmaz(tmp_path, monkeypatch):
    (tmp_path / "klipci").mkdir()
    (tmp_path / "klipci" / "__init__.py").write_text('SURUM = "2026.11.20-1"\n')
    (tmp_path / "config.yaml").write_text("bot_token: GIZLI")
    (tmp_path / "BASLAT.bat").write_text("eski")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Gta6-abc/klipci/__init__.py", 'SURUM = "2026.11.20-9"\n')
        z.writestr("Gta6-abc/klipci/yeni.py", "x = 1\n")
        z.writestr("Gta6-abc/config.yaml", "bot_token: ''")
        z.writestr("Gta6-abc/config.example.yaml", "ornek")
        z.writestr("Gta6-abc/BASLAT.bat", "yeni")
        z.writestr("Gta6-abc/klipler/x.mp4", "no")
    monkeypatch.setattr(g, "KOK", tmp_path)
    monkeypatch.setattr(g, "_indir", lambda url: buf.getvalue())
    n = g.guncelle({"baslat.bat"})
    assert n == 3
    assert g.yerel_surum() == "2026.11.20-9"
    assert (tmp_path / "config.yaml").read_text() == "bot_token: GIZLI"
    assert (tmp_path / "BASLAT.bat").read_text() == "eski"
    assert not (tmp_path / "klipler").exists()
    assert g.guncelle({"baslat.bat"}) == 0   # aynı dosyalar tekrar yazılmaz


def test_surum_karsilastirma():
    assert g._surum_sayi("2026.11.20-10") > g._surum_sayi("2026.11.20-9")
    assert g._surum_sayi("2026.11.21-1") > g._surum_sayi("2026.11.20-12")
