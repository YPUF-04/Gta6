import json
from klipci.chat import parse_kick_event, parse_twitch_privmsg
from klipci.kurgu import chat_sec
from klipci.altyazi import Kelime, kelime_parcala, tr_buyuk


def test_twitch_privmsg():
    assert parse_twitch_privmsg(":ali!ali@ali.tmi.twitch.tv PRIVMSG #xqc :LMAO no way") == ("ali", "LMAO no way")
    assert parse_twitch_privmsg("@badge=1;color=#fff :ali!ali@ali.tmi.twitch.tv PRIVMSG #xqc :hi :)") == ("ali", "hi :)")
    assert parse_twitch_privmsg(":tmi.twitch.tv 001 justinfan1 :Welcome") is None


def test_kick_event():
    raw = json.dumps({"event": "App\\Events\\ChatMessageEvent",
                      "data": json.dumps({"content": "KEKW", "sender": {"username": "veli"}})})
    assert parse_kick_event(raw) == ("veli", "KEKW")
    assert parse_kick_event('{"event":"pusher:pong"}') is None


def test_chat_sec_ust_uste_binmez():
    msgs = [(i * 0.2, f"u{i}", "LMAO") for i in range(100)]
    sec = chat_sec(msgs, 15, satir=3)
    assert sec and all(0 <= b < e <= 15 for b, e, *_ in sec)
    for sl in range(3):
        ayni = [x for x in sec if x[2] == sl]
        assert all(a[1] <= b[0] for a, b in zip(ayni, ayni[1:]))


def test_chat_sec_link_ve_uzun_atlanir():
    sec = chat_sec([(1, "a", "http://spam.com"), (2, "b", "x" * 80), (3, "c", "W")], 10)
    assert [m for *_, m in sec] == ["W"]


def test_altyazi():
    k = [Kelime(0, .3, "bu"), Kelime(.3, .6, "ne"), Kelime(.6, .9, "lan"), Kelime(.9, 1.2, "abi")]
    parca = kelime_parcala(k)
    assert [x[2] for x in parca] == ["bu ne lan", "abi"]
    assert parca[0][3][1] == (.3, .6, "ne")
    assert tr_buyuk("şaka mı bu iyi") == "ŞAKA MI BU İYİ"


def test_kick_emote_temizle():
    from klipci.chat import emote_temizle, parse_kick_event
    assert emote_temizle("[emote:6406295:collectiblesCarRe] haha [emote:1:KEKW]") == "haha KEKW"
    raw = json.dumps({"event": "App\\Events\\ChatMessageEvent",
                      "data": json.dumps({"content": "[emote:5747991:collectiblespeepo]", "sender": {"username": "z"}})})
    assert parse_kick_event(raw) == ("z", "💀")


def test_chat_az_ve_patlama_aninda():
    msgs = [(i * 0.2, f"u{i}", "LMAO" if i % 2 else "hello there") for i in range(250)]
    sec = chat_sec(msgs, 50, an=20)
    assert 1 <= len(sec) <= 5
    assert all(17 <= b <= 32 for b, *_ in sec)
    assert all(m == "LMAO" for *_, m in sec)


def test_ass_her_duzen_tepki_ile(tmp_path):
    from klipci.kurgu import ass_yaz
    alt = [(0.2, 2.0, "Oh my god", [(0.2, 0.6, "Oh"), (0.6, 1.0, "my"), (1.0, 2.0, "god")])]
    for duzen in ("yuz", "tek", "tweet"):
        (tmp_path / duzen).mkdir()
        ass_yaz(tmp_path / duzen / "a.ass", 10, "başlık", "🎥 x", "@y", alt, [], duzen,
                {"ad": "A", "kullanici": "@y", "ust": "U"}, (3.0, "chat koptu 😭"))
        assert "chat koptu" in (tmp_path / duzen / "a.ass").read_text(encoding="utf-8")


def test_isim_yoksa_ekranda_isim_yok(tmp_path):
    from klipci.kurgu import ass_yaz
    ass_yaz(tmp_path / "a.ass", 10, "", "🎥 twitch.tv/x", "", [], [], "tweet", {"ad": "", "kullanici": "", "ust": "BAŞLIK"})
    m = (tmp_path / "a.ass").read_text(encoding="utf-8")
    assert ",TAd," not in m and ",TAvatar," not in m and ",TKul," not in m and "BAŞLIK" in m
    ass_yaz(tmp_path / "b.ass", 10, "", "🎥 x", "", [], [], "yuz")
    assert "ImzaYuz" not in (tmp_path / "b.ass").read_text(encoding="utf-8").split("[Events]")[1]


def test_uydurma_altyazi_elenir():
    from klipci.altyazi import gercek_konusma_mi
    assert gercek_konusma_mi("bro what is he doing", 0.1, -0.3)
    assert not gercek_konusma_mi(" Thank you for watching!", 0.1, -0.3)
    assert not gercek_konusma_mi("Altyazı M.K.", 0.2, -0.5)
    assert not gercek_konusma_mi("you", 0.9, -1.2)
