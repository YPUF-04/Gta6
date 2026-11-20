"""TEST.bat: her parçayı gerçek yayınlarla dener, ne çalışıyor ne çalışmıyor tek tek yazar.

Her platformda (Twitch, Kick, YouTube): en çok izlenen GTA 6 yayınını bul -> chat'e bağlan ->
40 sn kaydet -> 20 sn'lik klip kes -> dikey video yap -> Telegram'a yolla.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import time
import traceback
from pathlib import Path

import httpx
import yaml

from . import kesif, yuz
from .chat import kick_chat, twitch_chat, youtube_chat
from .kayit import Kaydedici, arac
from .kurgu import ass_yaz, chat_sec, dikey_video
from .telegram import Bot

KOK = Path(__file__).resolve().parent.parent
SONUC: list[tuple[str, bool, str]] = []


def yaz(ad: str, ok: bool, detay: str = "") -> None:
    SONUC.append((ad, ok, detay))
    print(f"  {'✅' if ok else '❌'} {ad}" + (f"  —  {detay}" if detay else ""), flush=True)


async def platform_dene(ad: str, kesifci, bot: Bot, klasor: Path) -> None:
    print(f"\n=== {ad.upper()} ===", flush=True)
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            bulunan = await kesifci.bul(c, 10)
    except Exception as e:  # noqa: BLE001
        yaz(f"{ad}: yayın bulma", False, str(e)[:200])
        return
    yaz(f"{ad}: yayın bulma", bool(bulunan),
        f"{len(bulunan)} GTA 6 yayını, en büyüğü: {bulunan[0][0].gorunen} ({bulunan[0][1]} izleyici)" if bulunan
        else "şu an hiç GTA 6 yayını bulunamadı")
    if not bulunan:
        return

    # en büyük birkaç yayından ilk çalışanı dene
    for k, _ in bulunan[:3]:
        url, room = k.url, None
        if k.platform == "kick":
            b = await asyncio.to_thread(kesif.kick_bilgi, k.ad)
            if not b or not b.get("chatroom_id"):
                yaz(f"{ad}: kanal bilgisi ({k.ad})", False, "kick.com bilgi vermedi")
                continue
            room = b["chatroom_id"]
            if b.get("playback_url"):
                url = "hls://" + b["playback_url"]
        mesajlar: list = []

        def gelen(ts, kim, metin):
            mesajlar.append((ts, kim, metin))

        if k.platform == "twitch":
            chat = twitch_chat(k.ad, gelen)
        elif k.platform == "kick":
            chat = kick_chat(room, gelen, k.ad)
        else:
            chat = youtube_chat(k.ad, gelen)
        gorev = asyncio.create_task(chat)
        kayit = Kaydedici(url, klasor / f"tampon_{ad}", "720p,720p60,best", 9999)
        bas = time.time()
        kayit.baslat()
        print(f"  … {k.gorunen} izleniyor (40 sn bekle)", flush=True)
        await asyncio.sleep(40)
        gorev.cancel()
        yaz(f"{ad}: chat okuma ({k.gorunen})", len(mesajlar) > 0, f"40 sn'de {len(mesajlar)} mesaj")
        parca = kayit.parcalar()
        yaz(f"{ad}: yayın kaydı", len(parca) >= 3, f"{len(parca)} parça kaydedildi")
        if len(parca) < 3:
            kayit.durdur()
            continue
        sonuc = await asyncio.to_thread(kayit.kes, parca[1][1], parca[1][1] + 20, klasor / f"{ad}.ts")
        kayit.durdur()
        if not sonuc:
            yaz(f"{ad}: klip kesme", False)
            continue
        yaz(f"{ad}: klip kesme", True)
        try:
            t0 = parca[1][1]
            analiz = await asyncio.to_thread(yuz.analiz_et, sonuc[0], sonuc[1], 20)
            print(f"  ℹ️ yüz kamerası: {'bulundu → üstte yüz, altta oyun' if analiz.facecam else 'bulunamadı → tek ekran düzeni'}",
                  flush=True)
            chat_pop = chat_sec([(t - t0, kim, m) for t, kim, m in mesajlar], 20)
            ass = klasor / f"{ad}.ass"
            ass_yaz(ass, 20, f"test: {ad} çalışıyor", f"🎥 {k.kredi}", "@test", [], chat_pop,
                    "yuz" if analiz.facecam else "tek")
            mp4 = klasor / f"TEST_{ad}.mp4"
            await asyncio.to_thread(dikey_video, sonuc[0], sonuc[1], 20, mp4, ass, 1.3, analiz.facecam)
            yaz(f"{ad}: dikey video", mp4.exists(), f"{mp4.stat().st_size // 1024} KB")
        except Exception as e:  # noqa: BLE001
            yaz(f"{ad}: dikey video", False, str(e)[:200])
            return
        if bot.chat_id:
            try:
                await bot.video_gonder(mp4, f"🧪 TEST — {ad} — {k.gorunen}\n(bu bir test klibi, silebilirsin)", "test")
                yaz(f"{ad}: Telegram'a video", True, "telefonuna bak")
            except Exception as e:  # noqa: BLE001
                yaz(f"{ad}: Telegram'a video", False, str(e)[:200])
        del bas
        return


async def ana() -> None:
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8")) or {}
    print("=== TEMEL ===", flush=True)
    try:
        yaz("FFmpeg", bool(arac("ffmpeg")))
    except Exception as e:  # noqa: BLE001
        yaz("FFmpeg", False, str(e))
        return
    try:
        import cv2  # noqa: F401
        yaz("Görüntü paketi (yüz bulma)", True)
    except Exception:  # noqa: BLE001
        yaz("Görüntü paketi (yüz bulma)", False, "KURULUM.bat'ı tekrar çalıştır")
    try:
        import faster_whisper  # noqa: F401
        yaz("Altyazı paketi", True)
    except Exception:  # noqa: BLE001
        yaz("Altyazı paketi", False, "kurulu değil — videolar altyazısız çıkar")

    tg = cfg.get("telegram") or {}
    durum = {}
    try:
        import json
        durum = json.loads((KOK / "durum.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    bot = Bot(tg.get("bot_token", ""), tg.get("chat_id") or durum.get("chat_id", ""), lambda _c: None)
    if not bot.token:
        yaz("Telegram", False, "config.yaml'da bot_token boş")
    elif not bot.chat_id:
        yaz("Telegram", False, "önce BASLAT.bat'ı aç ve botuna /start yaz, sonra testi tekrar çalıştır")
    else:
        try:
            await bot.mesaj("🧪 Test başladı. Birkaç dakika içinde her platformdan bir test klibi gelecek.")
            yaz("Telegram", True, "telefonuna mesaj gitti")
        except Exception as e:  # noqa: BLE001
            yaz("Telegram", False, str(e)[:200])

    ob = cfg.get("otomatik_bul") or {}
    eski = (cfg.get("kanallar") or {}).get("twitch_otomatik_kesif") or {}
    from .oyun import ayarla
    oyun = ob.get("oyun_adi", ayarla(cfg).ad)
    klasor = KOK / "klipler" / "_test"
    shutil.rmtree(klasor, ignore_errors=True)
    klasor.mkdir(parents=True, exist_ok=True)
    platformlar = {
        "twitch": kesif.TwitchKesif(oyun, ob.get("twitch_client_id", eski.get("client_id", "")),
                                    ob.get("twitch_client_secret", eski.get("client_secret", ""))),
        "kick": kesif.KickKesif(oyun, ob.get("kick_client_id", ""), ob.get("kick_client_secret", "")),
        "youtube": kesif.YoutubeKesif(ob.get("youtube_arama", "")),
    }
    secim = [a.lower() for a in sys.argv[1:]] or list(platformlar)
    for ad in secim:
        try:
            await platform_dene(ad, platformlar[ad], bot, klasor)
        except Exception as e:  # noqa: BLE001
            yaz(f"{ad}: beklenmeyen hata", False, f"{e}")
            traceback.print_exc()

    print("\n================ ÖZET ================")
    for ad, ok, detay in SONUC:
        print(f"{'✅' if ok else '❌'} {ad}" + (f"  —  {detay}" if detay else ""))
    hata = sum(1 for _, ok, _ in SONUC if not ok)
    print("======================================")
    print("HER ŞEY ÇALIŞIYOR 🎉" if not hata else f"{hata} sorun var. Bu pencerenin ekran görüntüsünü at.")
    (KOK / "logs").mkdir(exist_ok=True)
    (KOK / "logs" / "test_sonucu.txt").write_text(
        "\n".join(f"{'OK ' if ok else 'HATA'} {ad} — {d}" for ad, ok, d in SONUC), encoding="utf-8")
    if bot.chat_id and bot.token:
        try:
            await bot.mesaj("🧪 Test bitti:\n" + "\n".join(f"{'✅' if ok else '❌'} {ad}" for ad, ok, _ in SONUC))
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    import logging
    logging.basicConfig(level=logging.WARNING, format="    %(name)s: %(message)s")
    asyncio.run(ana())


if __name__ == "__main__":
    main()
