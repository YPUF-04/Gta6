import json
from klipci.kesif import Kanal, _sayi, kick_site_ayikla, twitch_gql_ayikla, youtube_arama_ayikla
from klipci.chat import kick_pub_ayikla, youtube_chat_ayikla


def test_twitch_gql():
    j = {"data": {"game": {"streams": {"edges": [
        {"node": {"viewersCount": 50000, "broadcaster": {"login": "kaicenat", "displayName": "KaiCenat"}}},
        {"node": {"viewersCount": 10, "broadcaster": None}}]}}}}
    out = twitch_gql_ayikla(j)
    assert out == [(Kanal("twitch", "kaicenat"), 50000)]
    assert out[0][0].isim == "KaiCenat"


def test_kick_site_sadece_gta():
    j = {"data": {"livestreams": [
        {"channel": {"slug": "adinross"}, "viewer_count": 30000, "category": {"name": "Grand Theft Auto VI"}},
        {"channel": {"slug": "baskasi"}, "viewer_count": 9000, "category": {"name": "Just Chatting"}}]}}
    assert [(k.ad, v) for k, v in kick_site_ayikla(j)] == [("adinross", 30000)]


def test_youtube_arama():
    data = {"contents": [{"videoRenderer": {
        "videoId": "abcdefghijk", "title": {"runs": [{"text": "GTA 6 LIVE - first day!"}]},
        "ownerText": {"runs": [{"text": "SomeStreamer"}]},
        "viewCountText": {"runs": [{"text": "12,345"}, {"text": " watching"}]},
        "badges": [{"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_LIVE_NOW", "label": "LIVE"}}]}},
        {"videoRenderer": {"videoId": "zzzzzzzzzzz", "title": {"simpleText": "Minecraft"},
                           "viewCountText": {"simpleText": "5 watching"}}}]}
    out = youtube_arama_ayikla(data)
    assert len(out) == 1
    k, v = out[0]
    assert (k.platform, k.ad, k.isim, v) == ("youtube", "abcdefghijk", "SomeStreamer", 12345)
    assert k.url.endswith("abcdefghijk") and "SomeStreamer" in k.kredi


def test_sayi():
    assert _sayi("12,345 watching") == 12345
    assert _sayi("1.2K") == 1200
    assert _sayi(77) == 77


def test_kick_centrifugo_pub():
    ic = json.dumps({"content": "KEKW", "sender": {"username": "ali"}})
    cer = {"push": {"channel": "chatrooms.1.v2", "pub": {"data": {"event": "App\\Events\\ChatMessageEvent", "data": ic}}}}
    assert kick_pub_ayikla(cer) == ("ali", "KEKW")
    assert kick_pub_ayikla({"id": 1, "connect": {}}) is None


def test_youtube_chat():
    j = {"continuationContents": {"liveChatContinuation": {
        "continuations": [{"timedContinuationData": {"continuation": "NEXT", "timeoutMs": 2000}}],
        "actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
            "message": {"runs": [{"text": "LMAO "}, {"emoji": {"emojiId": "x", "shortcuts": [":skull:"]}}]},
            "authorName": {"simpleText": "veli"}, "timestampUsec": "1795000000000000"}}}}]}}}
    msgs, cont, bekle = youtube_chat_ayikla(j)
    assert msgs == [(1795000000.0, "veli", "LMAO :skull:")]
    assert cont == "NEXT" and bekle == 2.0


def test_kanal_coz():
    from klipci.kesif import kanal_coz
    assert kanal_coz("https://www.twitch.tv/KaiCenat") == ("twitch", "kaicenat")
    assert kanal_coz("kick.com/adinross?x=1") == ("kick", "adinross")
    assert kanal_coz("https://youtube.com/@IShowSpeed/live") == ("youtube", "@IShowSpeed")
    assert kanal_coz("twitch xqc") == ("twitch", "xqc")
    assert kanal_coz("kick Adinross") == ("kick", "adinross")
    assert kanal_coz("yt IShowSpeed") == ("youtube", "@IShowSpeed")
    assert kanal_coz("merhaba nasılsın") is None


def test_sablon_yapay_degil():
    from klipci.yazar import Yazar, paylasim_metni
    v = Yazar().yaz("tr", "KaiCenat", "twitch", [], "en", [], [])
    assert v["baslik"] == ""
    assert "KaiCenat" in v["aciklama"] and v["hashtagler"] == ["#kaicenat", "#gta6"]
    m = paylasim_metni(v, Kanal("twitch", "kaicenat", "KaiCenat"), "tr")
    assert "#kaicenat #gta6" in m and "twitch.tv/kaicenat" in m
    assert "sonuna kadar" not in m.lower()


def test_kick_kategori():
    import json
    from klipci.kesif import kick_kategori_ayikla, kick_kategori_slug, dil_kodu
    assert kick_kategori_slug("Grand Theft Auto VI") == "grand-theft-auto-vi"
    assert kick_kategori_slug("Grand Theft Auto VI (GTA)") == "grand-theft-auto-vi"
    assert dil_kodu("Turkish") == "tr" and dil_kodu("English") == "en" and dil_kodu("en") == "en"
    j = {"data": [{"is_live": True, "viewer_count": 6511, "language": "Turkish",
                   "channel": {"slug": "tepki", "user": {"username": "Tepki"}}},
                  {"is_live": True, "viewer_count": 17930, "language": "English", "channel": {"slug": "xqc"}}]}
    out = kick_kategori_ayikla(j)
    assert [(k.ad, k.isim, k.dil, v) for k, v in out] == [("tepki", "Tepki", "tr", 6511), ("xqc", "xqc", "en", 17930)]
