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
