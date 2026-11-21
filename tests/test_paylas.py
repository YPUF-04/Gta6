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


def test_facebook_reels_ve_sayfa_secimi(tmp_path):
    def isle(req):
        if req.url.path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": [{"id": "11", "name": "GTA 6 TR", "access_token": "PT1"},
                                                      {"id": "22", "name": "GTA 6 EN", "access_token": "PT2"}]})
        if req.url.path.endswith("/22/video_reels"):
            assert dict(httpx.QueryParams(req.content.decode()))["access_token"] == "PT2"
            return httpx.Response(200, json={"video_id": "V9", "upload_url": "https://rupload.facebook.com/video-upload/v21.0/V9", "success": True})
        if req.url.host == "rupload.facebook.com":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"error": {"message": "yok"}})
    h = httpx.Client(transport=httpx.MockTransport(isle))
    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"1")
    assert paylas.Facebook("UT|GTA 6 EN", h).reels(mp4, "x") == "https://www.facebook.com/reel/V9"
    try:
        paylas.Facebook("UT", h).sayfa()
        assert False
    except paylas.PaylasimHatasi as e:
        assert "birden fazla" in str(e)


def test_threads_videosu(tmp_path):
    def isle(req):
        if req.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "7", "username": "gtatr"})
        if req.url.path.endswith("/7/threads"):
            assert "video_url=https" in req.content.decode()
            return httpx.Response(200, json={"id": "C7"})
        if req.url.path.endswith("/C7"):
            return httpx.Response(200, json={"status": "FINISHED"})
        if req.url.path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "T7"})
        return httpx.Response(200, json={"permalink": "https://threads.net/@gtatr/post/x"})
    th = paylas.Threads("TT", tmp_path / "th.json", httpx.Client(transport=httpx.MockTransport(isle)), bekle=0)
    assert th.video("https://cdn.example/v.mp4", "x").startswith("https://threads.net")


def test_performans_raporu_ve_oncelik(tmp_path):
    import time as _t
    from klipci.performans import Performans
    p = Performans(tmp_path / "ist.json")
    veriler = {"kai": [20000, 30000], "xqc": [9000, 11000], "abc": [1000, 1200]}
    i = 0
    for y, izl in veriler.items():
        for v in izl:
            i += 1
            p.kaydet(f"20261121_10000{i}_{y}_EN", "EN", y, {"instagram": f"m{i}"})
    sayilar = {f"m{i}": v for i, v in enumerate([x for l in veriler.values() for x in l], 1)}
    assert p.guncelle(lambda plat, kimlik, hesap: {"izlenme": sayilar[kimlik], "begeni": sayilar[kimlik] // 10}) == 6
    r = p.rapor()
    assert "En çok izlenenler" in r and "1. kai" in r and "Daha çok paylaşacağız: kai" in r and "abc" in r
    assert p.yayinci_carpani("kai") > 1.2 and p.yayinci_carpani("abc") < 0.9


def test_ig_istatistik(tmp_path):
    def isle(req):
        if req.url.path.endswith("/me"):
            return httpx.Response(200, json={"user_id": "1", "username": "x"})
        if req.url.path.endswith("/M1/insights"):
            return httpx.Response(200, json={"data": [{"name": "views", "values": [{"value": 1500}]},
                                                      {"name": "likes", "values": [{"value": 90}]},
                                                      {"name": "comments", "values": [{"value": 4}]}]})
        return httpx.Response(404, json={"error": {"message": "yok"}})
    ig = paylas.Instagram("T", tmp_path / "ig.json", httpx.Client(transport=httpx.MockTransport(isle)))
    assert paylas.ig_istatistik(ig, "M1") == {"izlenme": 1500, "begeni": 90, "yorum": 4, "paylasim": 0, "kaydetme": 0}


def test_threads_instagram_olmazsa_facebook_kopyasi(tmp_path):
    denenen = []

    def isle(req):
        if req.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "7", "username": "gtaen"})
        if req.url.path.endswith("/7/threads"):
            adres = dict(httpx.QueryParams(req.content.decode()))["video_url"]
            denenen.append(adres)
            return httpx.Response(200, json={"id": "IG" if "instagram" in adres else "FB"})
        if req.url.path.endswith("/IG"):
            return httpx.Response(200, json={"status": "ERROR", "error_message": "UNKNOWN"})
        if req.url.path.endswith("/FB"):
            return httpx.Response(200, json={"status": "FINISHED"})
        if req.url.path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "T1"})
        return httpx.Response(200, json={"permalink": "https://threads.net/@gtaen/post/1"})
    th = paylas.Threads("TT", tmp_path / "th.json", httpx.Client(transport=httpx.MockTransport(isle)), bekle=0)
    assert th.video(["https://instagram.cdn/v.mp4", "https://fbcdn/v.mp4"], "x").startswith("https://threads.net")
    assert denenen == ["https://instagram.cdn/v.mp4", "https://instagram.cdn/v.mp4", "https://fbcdn/v.mp4"]


def test_wav_oku(tmp_path):
    import subprocess
    from klipci.altyazi import wav_oku
    w = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2", "-ac", "1", "-ar", "16000", str(w)],
                   check=True)
    x = wav_oku(w)
    assert len(x) == 32000 and str(x.dtype) == "float32" and 0 < abs(x).max() <= 1
