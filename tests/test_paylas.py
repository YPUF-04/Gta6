import json

import httpx

from klipci import paylas


def test_instagram_reels_akisi(tmp_path):
    istekler = []

    def isle(req: httpx.Request) -> httpx.Response:
        istekler.append((req.method, req.url.host, req.url.path))
        if req.url.path.endswith("/me"):
            return httpx.Response(200, json={"user_id": "123", "username": "gta6klip"})
        if req.url.path.endswith("/123/media"):
            return httpx.Response(200, json={"id": "C1", "uri": "https://rupload.facebook.com/ig-api-upload/v21.0/C1"})
        if req.url.host == "rupload.facebook.com":
            assert req.headers["file_size"] == "5" and req.headers["Authorization"] == "OAuth TOK"
            return httpx.Response(200, json={"success": True})
        if req.url.path.endswith("/C1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if req.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M9"})
        if req.url.path.endswith("/M9"):
            return httpx.Response(200, json={"permalink": "https://instagram.com/reel/abc"})
        return httpx.Response(404, json={"error": {"message": "yok"}})

    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"12345")
    ig = paylas.Instagram("TOK", tmp_path / "ig.json", httpx.Client(transport=httpx.MockTransport(isle)), bekle=0)
    assert ig.reels(mp4, "çok iyi 😂 #gta6") == "https://instagram.com/reel/abc"
    assert ("POST", "graph.instagram.com", "/v21.0/123/media_publish") in istekler


def test_instagram_hata_anlasilir(tmp_path):
    def isle(req):
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})
    ig = paylas.Instagram("X", tmp_path / "ig.json", httpx.Client(transport=httpx.MockTransport(isle)), bekle=0)
    try:
        ig.hesap()
        assert False
    except paylas.PaylasimHatasi as e:
        assert "Invalid OAuth" in str(e)


def test_youtube_yukleme(tmp_path):
    istemci = tmp_path / "client_secret.json"
    istemci.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
    jeton = tmp_path / "TR.json"
    jeton.write_text(json.dumps({"refresh_token": "R"}))

    def isle(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "A"})
        if req.method == "POST" and req.url.path == "/upload/youtube/v3/videos":
            govde = json.loads(req.content)
            assert govde["snippet"]["categoryId"] == "20" and req.headers["Authorization"] == "Bearer A"
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/x?id=1"})
        if req.method == "PUT":
            return httpx.Response(200, json={"id": "VID1"})
        return httpx.Response(404)

    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"abc")
    yt = paylas.YouTube(istemci, jeton, httpx.Client(transport=httpx.MockTransport(isle)))
    assert yt.bagli_mi()
    assert yt.yukle(mp4, "bu adam ne yaptı #shorts", "açıklama", ["#gta6"]) == "https://youtube.com/shorts/VID1"


def test_paylasim_durumu_komutu(tmp_path, monkeypatch):
    import asyncio
    from tests.test_komut import _app
    u = _app(tmp_path, monkeypatch)
    m = asyncio.run(u._komut("/paylasim"))
    assert "[TR]" in m and "bağlı değil" in m and "TikTok" in m


def test_youtube_cihaz_kodu(tmp_path):
    istemci = tmp_path / "c.json"
    istemci.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
    cevaplar = iter([{"error": "authorization_pending"}, {"refresh_token": "R1", "access_token": "A"}])

    def isle(req):
        if req.url.path == "/device/code":
            return httpx.Response(200, json={"device_code": "D", "user_code": "ABCD-EFGH",
                                             "verification_url": "https://www.google.com/device", "interval": 1,
                                             "expires_in": 60})
        return httpx.Response(200, json=next(cevaplar))
    h = httpx.Client(transport=httpx.MockTransport(isle))
    c = paylas.youtube_cihaz_baslat(istemci, h)
    assert c["user_code"] == "ABCD-EFGH"
    jeton = tmp_path / "TR.json"
    assert paylas.youtube_cihaz_bekle(istemci, c, jeton, h, uyku=lambda s: None) == "bağlandı"
    assert json.loads(jeton.read_text())["refresh_token"] == "R1"


def test_bagla_komutlari(tmp_path, monkeypatch):
    import asyncio
    from tests.test_komut import _app
    u = _app(tmp_path, monkeypatch)
    run = lambda m: asyncio.run(u._komut(m))
    assert "INSTAGRAM" in run("/bagla")
    monkeypatch.setattr(paylas.Instagram, "hesap", lambda self: {"id": "1", "kullanici": "gta6tr"})
    tok = "IGAA" + "x" * 150
    assert "yarım" in run("/bagla instagram TR IGAAxxxx...")
    assert "benzemiyor" in run("/bagla instagram TR anahtar")
    assert "@gta6tr" in run(f"/bagla instagram TR {tok}")
    assert next(h for h in u._hesaplar() if h["ad"] == "TR")["instagram_token"] == tok
    assert "JSON" in run("/bagla youtube TR")
    js = json.dumps({"installed": {"client_id": "c", "client_secret": "s"}}).encode()
    assert "kaydedildi" in asyncio.run(u._belge(js, "client_secret.json", ""))
    assert "tanımadım" in asyncio.run(u._belge(b"\xff", "x.bin", ""))


def test_instagram_unified_login_anahtari(tmp_path):
    """Yeni Meta uygulamaları: graph.instagram.com anahtarı tanımaz, graph.facebook.com ile çalışır."""
    istekler = []

    def isle(req):
        istekler.append((req.url.host, req.url.path))
        if req.url.host == "graph.instagram.com":
            return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})
        if req.url.path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": [{"instagram_business_account": {"id": "1784", "username": "gtatr"}}]})
        if req.url.path.endswith("/1784/media"):
            return httpx.Response(200, json={"id": "C2", "uri": "https://rupload.facebook.com/ig-api-upload/v21.0/C2"})
        if req.url.host == "rupload.facebook.com":
            return httpx.Response(200, json={"success": True})
        if req.url.path.endswith("/C2"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if req.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M2"})
        return httpx.Response(200, json={"permalink": "https://instagram.com/reel/x"})
    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"1")
    ig = paylas.Instagram("FBTOK", tmp_path / "ig.json", httpx.Client(transport=httpx.MockTransport(isle)), bekle=0)
    assert ig.hesap() == {"id": "1784", "kullanici": "gtatr"}
    assert ig.reels(mp4, "x") == "https://instagram.com/reel/x"
    assert ("graph.facebook.com", "/v21.0/1784/media_publish") in istekler
    # hesap numarası elle verilirse
    ig2 = paylas.Instagram("FBTOK|1784", tmp_path / "ig2.json", httpx.Client(transport=httpx.MockTransport(isle)))
    assert ig2.ig_id == "1784" and ig2.token == "FBTOK"


def test_tek_anahtar_iki_hesap_karismaz(tmp_path):
    def isle(req):
        if req.url.host == "graph.instagram.com":
            return httpx.Response(400, json={"error": {"message": "Invalid OAuth"}})
        if req.url.path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": [{"instagram_business_account": {"id": "1", "username": "gtatr"}},
                                                      {"instagram_business_account": {"id": "2", "username": "gtaen"}}]})
        return httpx.Response(400, json={"error": {"message": "yok"}})
    h = httpx.Client(transport=httpx.MockTransport(isle))
    assert paylas.Instagram("T|@gtaen", tmp_path / "a.json", h).hesap()["id"] == "2"
    assert paylas.Instagram("T|gtatr", tmp_path / "b.json", h).hesap()["id"] == "1"
    try:
        paylas.Instagram("T", tmp_path / "c.json", h).hesap()
        assert False
    except paylas.PaylasimHatasi as e:
        assert "birden fazla" in str(e)
