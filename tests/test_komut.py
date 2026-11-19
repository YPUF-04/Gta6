import asyncio

from klipci import kesif
from klipci.uygulama import Uygulama


def _app(tmp_path, monkeypatch):
    monkeypatch.setattr(kesif, "kick_bilgi", lambda ad: {"canli": True, "chatroom_id": 1})
    monkeypatch.setattr(kesif, "yayinda_mi", lambda k: False)
    monkeypatch.setattr(kesif, "youtube_kanal_canli", lambda h: None)
    cfg = {"telegram": {"bot_token": "x"}, "klasor": str(tmp_path / "k"),
           "kanallar": {"twitch": ["xqc"], "yasakli": ["kotu"]}, "altyazi": {"acik": False}}
    return Uygulama(cfg, tmp_path)


def test_ekle_cikar_yasakla(tmp_path, monkeypatch):
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    assert "eklendi" in run("/ekle kick adinross") and "yayında" in run("/ekle kick adinross")
    assert "eklendi" in run("https://www.twitch.tv/KaiCenat")
    assert "değil" in run("/ekle twitch kaicenat")
    assert u._liste("kick") == ["adinross"]
    assert u._liste("twitch") == ["xqc", "kaicenat"]
    assert "çıkarıldı" in run("/cikar twitch xqc")
    assert u._liste("twitch") == ["kaicenat"]
    assert "yasaklandı" in run("/yasakla adinross")
    assert {"kotu", "adinross"} <= u._yasaklar()
    assert "kaldırıldı" in run("/yasak_kaldir adinross")
    liste = run("/liste")
    assert "kaicenat" in liste and "kotu" in liste
    assert "/ekle" in run("/yardim")
    assert run("selam") == ""
    # kalıcı: yeni uygulama aynı listeyi görür
    assert _app(tmp_path, monkeypatch)._liste("twitch") == ["kaicenat"]
