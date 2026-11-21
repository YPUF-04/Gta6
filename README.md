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

**Yayıncı nasıl seçilir?** (en kolay yollar)

- Twitch için: `/twitch kaicenat` (birden çok: `/twitch kaicenat xqc jynxzi`)
- Kick için: `/kick adinross`
- YouTube için: `/youtube @IShowSpeed`
- Ya da yayının linkini bota at: `https://kick.com/adinross` → kendisi anlar.
- Hiçbir şey yapmazsan da en çok izlenen GTA 6 yayınlarını kendisi bulur.
- Liste görüp dokunarak seçmek istersen: `/yayinlar` → ⭐ izle, ⛔ asla.

**Telegram komutları** (Telegram'da `/` yazınca liste çıkar):

| Komut | Ne yapar |
|---|---|
| `/yayinlar` | Şu an açık GTA 6 yayınları — dokun: ⭐ izle, ⛔ asla klipleme |
| `/platform` | Twitch / Kick / YouTube aç-kapat; "otomatik bul" ya da "sadece benim seçtiklerim" |
| `/durum` | Neler izleniyor, kaç klip çıktı, altyazı hazır mı |
| `/plan` | Bugünün paylaşım saatleri |
| `/stok` | TR / EN hesaplarında kaç video hazır |
| `/sinir 30` | Aynı anda kaç yayın izlensin |
| `/gunluk 10` | Her hesap için günde kaç paylaşım |
| `/meme` | Şimdi meme videosu yap (her gün 10:00'da kendisi yapar) |
| `/isim @hesabim` | Videonun altındaki isim (sadece biri için: `/isim en @x`, kaldırmak: `/isim sil`) |
| `/hesap` | TR / EN hesaplarını aç-kapat |
| `/istatistik` | Beğenilerinden ne öğrendiği |
| `/ekle kick adinross` ya da link | Yayıncı ekler |
| `/cikar`, `/yasakla`, `/yasak_kaldir`, `/liste` | Listeyi yönetir |
| `/duraklat` / `/devam` | Kliplemeyi durdurur / başlatır |

## Video tarzları

- **Yüzü bulunan yayıncı:** üstte yayıncının kamerası, altta oyun; konuşma ortadaki çizgide kelime kelime, söylenen kelime mor kutuda (TikTok klip tarzı).
- **Yüzü olmayan / küçük yayıncı:** tweet tarzı — beyaz zemin, üstte senin sayfanın profili (fotoğraf, ad, @kullanıcı adı) ve büyük başlık, ortada kare oyun videosu.
  - Sayfa adı: `/ad GTA 6 Anları`
  - Büyük başlık: `/ustyazi GÜNÜMÜ GÜZELLEŞTİREN KLİPLER` (sadece İngilizce hesap: `/ustyazi en ...`)
  - Profil fotoğrafı: bota fotoğraf at, açıklamasına `/profil` yaz.

## Günlük akış

1. Klip gelir: üstte yayıncının yüzü, altta oyun, chat mesajları, altyazı, puan (⭐ 7.8/10) ve neden o puanı aldığı.
2. **✅ Stoğa ekle** ya da **🗑 Sil**. Her kararından neyi sevdiğini öğrenir, sonraki klipleri ona göre puanlar.
3. Her gün her hesap için en iyi 5 video, günün farklı saatlerine dağıtılır (saatler her gün değişir).
4. Saati gelince Telegram'a gelir: video + **Instagram / TikTok / YouTube** açıklamaları (dokununca kopyalanır).
   Paylaşınca **✅ Paylaştım**.
5. Her akşam 21:30'da yarın için stok durumu gelir (hedef: hesap başına 15 video).

## Güncelleme

Program kendini günceller, ZIP indirmene gerek yok:
- **BASLAT.bat** her açılışta yeni sürüm var mı bakar, varsa kurar.
- Program açıkken Telegram'a "🆕 Yeni sürüm var" gelir: **/guncelle** yazınca indirir, kurar, kendini yeniden başlatır.
- Elle istersen: **GUNCELLE.bat**.
`config.yaml`, Telegram bağlantın, klipler ve kurulu paketler korunur.

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


## 🤖 OTOMATİK PAYLAŞIM (ücretsiz)

Onayladığın (✅) klipler paylaşım saatinde **kendiliğinden** yüklenir. Telegram'da `/paylasim` yazınca neyin bağlı olduğunu görürsün.

| Platform | Durum |
|---|---|
| 📸 Instagram Reels | Otomatik, herkese açık (günde 50'ye kadar) |
| ▶️ YouTube Shorts | Otomatik. Google incelemesi bitene kadar **gizli** yüklenir (Google kuralı) |
| 🎵 TikTok | Elle: video + açıklama Telegram'a gelir (TikTok ücretsiz resmi yol vermiyor) |

### 📸 Instagram (her hesap için bir kez, ~15 dk)
1. Instagram uygulaması → Ayarlar → **Hesap türü ve araçlar** → **Profesyonel hesaba geç** → *İçerik üreticisi*.
2. Bilgisayarda **developers.facebook.com** → giriş yap → **Uygulamalarım** → **Uygulama oluştur**.
   Kullanım alanı olarak **"Instagram'da mesajları ve içeriği yönet"**i seç, adı `klipci` olsun.
3. Uygulamada sol menü **Uygulama rolleri → Roller → Kişi ekle → Instagram Test Kullanıcısı** → Instagram kullanıcı adını yaz.
   Telefonda Instagram → Ayarlar → **Uygulamalar ve internet siteleri → Test kullanıcısı davetleri** → **Kabul et**.
4. Uygulamada **Instagram → Instagram girişi ile API kurulumu → Erişim anahtarı oluştur → Hesap ekle** → Instagram'a giriş yap → çıkan uzun yazıyı (token) kopyala.
5. `config.yaml` → `hesaplar` → o hesabın `instagram_token: ""` tırnaklarının arasına yapıştır, kaydet, programı yeniden başlat.
   Anahtarı program kendisi yeniler (60 günde bitmez).

### ▶️ YouTube (bir kez, ~15 dk)
1. **console.cloud.google.com** → üstten **Yeni proje** (ad: `klipci-tr`).
2. **API'ler ve Hizmetler → Kitaplık** → **YouTube Data API v3** → **Etkinleştir**.
3. **OAuth izin ekranı** → *Harici* → uygulama adı `klipci`, e-postanı yaz → kaydet.
   **Hedef kitle → Uygulamayı yayınla (Üretime geçir)** de (yoksa bağlantı 7 günde bir kopar).
4. **Kimlik bilgileri → Kimlik bilgisi oluştur → OAuth istemci kimliği → Masaüstü uygulaması** → **JSON indir**.
5. İnen dosyanın adını `client_secret.json` yap, programın klasöründe `youtube` adında klasör aç, içine koy.
   (İki hesap için iki ayrı proje açarsan dosyaları `client_secret_TR.json` / `client_secret_EN.json` yap: her projenin günlük ~6 yükleme hakkı ayrı olur.)
6. **YOUTUBE_BAGLA.bat**'a çift tıkla → `TR` yaz → tarayıcıda kanalını seç → *"Google bu uygulamayı doğrulamadı"* çıkarsa **Gelişmiş → klipci'ye git** → **İzin ver**.
   EN hesabı için tekrar çalıştır, `EN` yaz.

Videolar önce **gizli** yüklenir: YouTube Studio'dan tek tıkla *Herkese açık* yap. Gizli olmaktan kurtulmak için Google'a ücretsiz
"YouTube API Services Audit" başvurusu yapılabilir (birkaç hafta sürer).
