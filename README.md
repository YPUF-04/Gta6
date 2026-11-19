# GTA 6 Klipçi 🎮✂️

Twitch, Kick ve YouTube'daki GTA 6 yayınlarını **kendisi bulur**, chat'in patladığı anları
(herkesin "LMAO", "NO WAY", "CLIP THAT" yazdığı an) **otomatik keser**, dikey
Reels/Shorts/TikTok videosuna çevirir ve **Telegram'dan telefonuna yollar**.
Sen sadece ✅ ya da 🗑 basarsın, beğendiğini paylaşırsın.

## Ne yapıyor?

1. **Yayın bulur.** Twitch, Kick ve YouTube'da o an GTA 6 oynayan en çok izlenen yayınları kendisi bulur ve aynı anda hepsini izler. İsim yazmana gerek yok.
2. **Chat'i sayar.** Her 10 saniyede kaç mesaj geldiğine bakar. Normalin 3 katına çıkınca bir şey olmuş demektir. "LMAO", "KEKW", "💀" ve "clip" gibi tepkiler ekstra puan alır.
3. **Geri sarıp keser.** Yayının son 4 dakikası bilgisayarında tutulur. Klip, patlamadan 22 saniye önce başlar ve 12 saniye sonra biter, çünkü chat olaydan sonra tepki verir.
4. **Kurgular.** Video 1080x1920 dikey olur:
   - arkada bulanık, ortada yakınlaştırılmış oyun görüntüsü,
   - üstte Türkçe başlık ("Chat buna inanamadı 💀"),
   - ekrana düşüp kaybolan chat mesajları,
   - kelime kelime çıkan büyük altyazı,
   - yayıncı adı ve senin sayfa adın.
5. **Yazar.** Claude API anahtarı varsa başlık, açıklama ve hashtag'leri Türkçe yazar, İngilizce konuşmayı Türkçe altyazıya çevirir ve klibe 1-10 arası viral puanı verir.
6. **Telegram'a yollar.** Telefonuna videoyla birlikte açıklama gelir:
   - **✅ Paylaşacağım:** video `klipler/hazir/TR/` klasörüne geçer. Açıklama ayrı mesaj olarak gelir, basılı tutup kopyalarsın.
   - **🗑 Sil:** video silinir.

## Kurulum (Windows, bir kere)

1. Bu klasörü bilgisayarına indir (GitHub → **Code → Download ZIP** → klasöre çıkart).
2. **Telegram botu aç:**
   - Telegram'da **@BotFather**'a yaz, `/newbot` gönder.
   - Bota bir isim ver. BotFather sana bir **token** verir (`123456:ABC...` gibi).
3. **`KURULUM.bat`'a çift tıkla.** Python, FFmpeg ve gerekli paketleri kendisi kurar, en sonda `config.yaml` dosyasını Not Defteri'nde açar.
4. Açılan dosyada `bot_token: ""` satırına token'ı yapıştır, kaydet, kapat.
5. *(Önerilir)* Türkçe başlık ve çeviri için https://console.anthropic.com adresinden bir API anahtarı al, `anthropic_api_key` satırına yapıştır.
6. **`TEST.bat`**'a çift tıkla. Her platformda gerçek bir yayına bağlanıp test klibi yapar ve neyin çalıştığını ✅ / ❌ ile yazar (3-4 dakika).

## Kullanım: aç / kapa

| | |
|---|---|
| **Aç** | `BASLAT.bat`'a çift tıkla. Siyah pencere açık kaldığı sürece çalışır. |
| **Kapa** | Siyah pencereyi kapat ya da `DURDUR.bat`'a çift tıkla. |

İlk açışta Telegram'da botuna **/start** yaz. Bot seni tanır ve klipleri sana yollamaya başlar.

**Telegram komutları** (Telegram'da `/` yazınca liste çıkar):

| Komut | Ne yapar |
|---|---|
| `/yayinlar` | Şu an açık GTA 6 yayınları — dokun: ⭐ izle, ⛔ asla klipleme |
| `/platform` | Twitch / Kick / YouTube aç-kapat; "otomatik bul" ya da "sadece benim seçtiklerim" |
| `/durum` | Neler izleniyor, kaç klip çıktı, altyazı hazır mı |
| `/plan` | Bugünün paylaşım saatleri |
| `/stok` | TR / EN hesaplarında kaç video hazır |
| `/isim @hesabim` | Videonun altındaki isim (sadece biri için: `/isim en @x`, kaldırmak: `/isim sil`) |
| `/hesap` | TR / EN hesaplarını aç-kapat |
| `/istatistik` | Beğenilerinden ne öğrendiği |
| `/ekle kick adinross` ya da link | Yayıncı ekler |
| `/cikar`, `/yasakla`, `/yasak_kaldir`, `/liste` | Listeyi yönetir |
| `/duraklat` / `/devam` | Kliplemeyi durdurur / başlatır |

## Günlük akış

1. Klip gelir: üstte yayıncının yüzü, altta oyun, chat mesajları, altyazı, puan (⭐ 7.8/10) ve neden o puanı aldığı.
2. **✅ Stoğa ekle** ya da **🗑 Sil**. Her kararından neyi sevdiğini öğrenir, sonraki klipleri ona göre puanlar.
3. Her gün her hesap için en iyi 5 video, günün farklı saatlerine dağıtılır (saatler her gün değişir).
4. Saati gelince Telegram'a gelir: video + **Instagram / TikTok / YouTube** açıklamaları (dokununca kopyalanır).
   Paylaşınca **✅ Paylaştım**.
5. Her akşam 21:30'da yarın için stok durumu gelir (hedef: hesap başına 15 video).

## Ayarlar (`config.yaml`)

- `otomatik_bul`: hangi platformlarda otomatik arasın, en az kaç izleyicili yayınlara baksın.
- `kanallar.twitch` / `kick` / `youtube`: kesin izlenmesini istediğin yayıncılar (isteğe bağlı).
- `yasakli`: asla kliplenmeyecek yayıncılar.
- `ayni_anda_en_fazla_kanal`: aynı anda kaç yayın izlensin. Her yayın yaklaşık 3 Mbps internet kullanır.
- `algilama.kat`: düşürürsen daha çok klip gelir, yükseltirsen daha az ama daha iyi klip gelir.
- `klip.once_sn` / `sonra_sn`: klibin uzunluğu.
- `chat_ekrani`: chat mesajları ekrana düşsün mü, aynı anda kaç tane görünsün.
- `altyazi.cihaz: cuda`: NVIDIA ekran kartın varsa altyazı çok daha hızlı çıkar.
- `hesaplar`: her hesap için ayrı dilde video üretilir. İngilizce sayfa açınca `EN` satırlarının başındaki `#` işaretlerini kaldır.

## Önemli uyarı ⚠️

Yayınlar yayıncılara aittir. İzinsiz kesip yüklemek telif ihlali (YouTube'da 3 ihlal = kanal kapanır) ya da "orijinal olmayan içerik" cezası getirebilir.

- Program her videoya ve açıklamaya yayıncının adını otomatik yazar. Bunu silme.
- İzin veren ya da klip kampanyası açan yayıncıları tercih et.
- Telif şikâyeti gelen yayıncıyı `yasakli` listesine ekle.

## Sorun çözme

- Kayıtlar `logs/klipci.log` dosyasında.
- **Kick chat bağlanmıyorsa:** Kick bazen bot korumasıyla engelliyor. Biraz sonra kendisi tekrar dener.
- **Altyazı yavaşsa:** `whisper_model: base` yap ya da `cihaz: cuda` kullan.
- **Telegram'a video gelmiyorsa:** botuna `/start` yazdığından emin ol.
