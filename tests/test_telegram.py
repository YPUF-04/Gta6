import asyncio

from klipci.telegram import Bot


def test_buton_hemen_cevap_sonra_islem():
    bot = Bot("x", "42", lambda c: None)
    cagrilar = []

    async def api(metod, **kw):
        cagrilar.append(metod)
        if metod == "editMessageText":
            raise RuntimeError("telegram editMessageText: Bad Request: message is not modified")
        return {}

    async def buton(veri):
        await asyncio.sleep(0.05)
        return ("✅ eklendi", "yeni menü", [[{"text": "a", "callback_data": "x:"}]])

    async def mesaj(m, **kw):
        cagrilar.append(("mesaj", m))

    bot._api, bot.on_buton, bot.mesaj = api, buton, mesaj
    u = {"callback_query": {"id": "1", "data": "ek:twitch:zarbex",
                            "message": {"message_id": 5, "chat": {"id": 42}}}}

    async def calis():
        await bot._isle(u)
        assert cagrilar == ["answerCallbackQuery"]          # önce hemen cevap
        await asyncio.gather(*bot._arka_gorevler)
    asyncio.run(calis())
    assert "editMessageText" in cagrilar and ("mesaj", "✅ eklendi") in cagrilar   # "not modified" sorun değil
