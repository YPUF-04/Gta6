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
