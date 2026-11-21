"""Otomatik paylaşım (ücretsiz, resmi yollar):

- Instagram Reels: Instagram'ın resmi sistemi (Instagram API, Instagram ile giriş). Profesyonel hesap +
  developers.facebook.com'dan alınan anahtar (token) gerekir. Herkese açık paylaşır, günde 50'ye kadar.
- YouTube Shorts: YouTube Data API. Google Cloud'dan indirilen client_secret.json + bir kez tarayıcıdan
  "izin ver". Google incelemesi bitene kadar videolar GİZLİ yüklenir (Google kuralı).
- TikTok: ücretsiz resmi yol yok (onaysız uygulama sadece gizli paylaşabilir) → Telegram'dan elle.
"""
from __future__ import annotations

import json
import logging
import socket
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

log = logging.getLogger("paylas")

IG_API = "https://graph.instagram.com/v21.0"
FB_API = "https://graph.facebook.com/v21.0"   # yeni uygulamalar: "Unified login" (sistem kullanıcısı anahtarı)
IG_YUKLEME = "https://rupload.facebook.com/ig-api-upload/v21.0/{cid}"
YT_YETKI = "https://accounts.google.com/o/oauth2/v2/auth"
YT_JETON = "https://oauth2.googleapis.com/token"
YT_YUKLEME = "https://www.googleapis.com/upload/youtube/v3/videos"
YT_KAPSAM = "https://www.googleapis.com/auth/youtube.upload"


class PaylasimHatasi(RuntimeError):
    pass


def _json(r: httpx.Response) -> dict:
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code >= 400 or (isinstance(j, dict) and j.get("error")):
        hata = j.get("error") if isinstance(j, dict) else None
        mesaj = (hata.get("message") if isinstance(hata, dict) else hata) or r.text[:200]
        raise PaylasimHatasi(f"{r.status_code}: {mesaj}")
    return j


# ============================ INSTAGRAM ============================

class Instagram:
    """Instagram Reels'e doğrudan bilgisayardan yükler (video herkese açık bir adrese konmadan)."""

    def __init__(self, token: str, kayit: Path, http: httpx.Client | None = None, bekle: float = 5.0):
        # "anahtar|instagram_hesap_id" biçimi de olur (Unified login'de hesap no'su gerekebilir)
        token, _, self.ig_id = (token or "").strip().partition("|")
        self.api = IG_API
        self.kayit = kayit
        self.http = http or httpx.Client(timeout=httpx.Timeout(120, connect=20))
        self.bekle = bekle
        d = self._oku()
        # config'teki anahtar değiştiyse yenisini kullan; değişmediyse daha önce yenilenmiş olanı
        if token and d.get("ilk") != token:
            d = {"ilk": token, "token": token, "t": time.time()}
            self._yaz(d)
        self.token = d.get("token") or token

    def _oku(self) -> dict:
        try:
            return json.loads(self.kayit.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _yaz(self, d: dict) -> None:
        self.kayit.parent.mkdir(parents=True, exist_ok=True)
        self.kayit.write_text(json.dumps(d), encoding="utf-8")

    def tazele(self) -> None:
        """Uzun süreli anahtar 60 gün geçerli; haftada bir yenilenir ki hiç bitmesin."""
        d = self._oku()
        if self.api == FB_API or time.time() - float(d.get("t", 0)) < 7 * 86400:
            return   # Unified login anahtarı hiç bitmez
        try:
            j = _json(self.http.get("https://graph.instagram.com/refresh_access_token",
                                    params={"grant_type": "ig_refresh_token", "access_token": self.token}))
            if j.get("access_token"):
                self.token = j["access_token"]
                d.update(token=self.token, t=time.time())
                self._yaz(d)
                log.info("Instagram anahtarı yenilendi")
        except Exception as e:  # noqa: BLE001
            log.warning("Instagram anahtarı yenilenemedi: %r", e)

    def hesap(self) -> dict:
        """Anahtarın türünü anla (Instagram girişi / Unified login) ve Instagram hesap numarasını bul."""
        if self.ig_id:   # hesap numarası verildiyse doğrudan
            for api in (FB_API, IG_API):
                try:
                    j = _json(self.http.get(f"{api}/{self.ig_id}", params={"fields": "id,username",
                                                                           "access_token": self.token}))
                    self.api = api
                    return {"id": str(j.get("id") or self.ig_id), "kullanici": j.get("username", "")}
                except PaylasimHatasi:
                    continue
        try:   # eski yöntem: Instagram girişi anahtarı
            j = _json(self.http.get(f"{IG_API}/me", params={"fields": "user_id,username", "access_token": self.token}))
            self.api = IG_API
            return {"id": str(j.get("user_id") or j.get("id")), "kullanici": j.get("username", "")}
        except PaylasimHatasi as ilk_hata:
            hata = ilk_hata
        # yeni yöntem: Unified login (Facebook anahtarı) — Instagram hesabını bağlı varlıklardan bul
        self.api = FB_API
        denemeler = [("me/accounts", {"fields": "instagram_business_account{id,username}"}),
                     ("me/businesses", {"fields": "instagram_business_accounts{id,username},"
                                                  "owned_instagram_accounts{id,username}"})]
        for yol, p in denemeler:
            try:
                j = _json(self.http.get(f"{FB_API}/{yol}", params={**p, "access_token": self.token}))
            except PaylasimHatasi as e:
                hata = e
                continue
            for x in j.get("data") or []:
                for alan in ("instagram_business_account", "instagram_business_accounts", "owned_instagram_accounts"):
                    v = x.get(alan)
                    adaylar = (v.get("data") if isinstance(v, dict) and "data" in v else [v]) if v else []
                    for ig in adaylar:
                        if ig and ig.get("id"):
                            return {"id": str(ig["id"]), "kullanici": ig.get("username", "")}
        raise PaylasimHatasi(f"Instagram hesabı bulunamadı ({hata}). Anahtarın yanına Instagram hesap numarasını "
                             "da yaz: /bagla instagram TR anahtar hesapno")

    def reels(self, mp4: Path, aciklama: str) -> str:
        """Reels paylaş, gönderinin linkini döndür."""
        self.tazele()
        uid = self.hesap()["id"]
        api = self.api
        j = _json(self.http.post(f"{api}/{uid}/media", data={
            "media_type": "REELS", "upload_type": "resumable", "caption": aciklama[:2200],
            "share_to_feed": "true", "access_token": self.token}))
        cid = j["id"]
        adres = j.get("uri") or IG_YUKLEME.format(cid=cid)
        veri = Path(mp4).read_bytes()
        _json(self.http.post(adres, content=veri, headers={
            "Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(len(veri))}))
        # Instagram videoyu işlerken bekle (genelde 20-60 sn)
        for _ in range(120):
            d = _json(self.http.get(f"{api}/{cid}", params={"fields": "status_code,status",
                                                                "access_token": self.token}))
            durum = d.get("status_code")
            if durum == "FINISHED":
                break
            if durum in ("ERROR", "EXPIRED"):
                raise PaylasimHatasi(f"Instagram videoyu işleyemedi: {d.get('status') or durum}")
            time.sleep(self.bekle)
        else:
            raise PaylasimHatasi("Instagram videoyu 10 dakikada işleyemedi")
        mid = _json(self.http.post(f"{api}/{uid}/media_publish",
                                   data={"creation_id": cid, "access_token": self.token}))["id"]
        try:
            return _json(self.http.get(f"{api}/{mid}", params={"fields": "permalink",
                                                                  "access_token": self.token})).get("permalink", "")
        except Exception:  # noqa: BLE001
            return ""


# ============================ YOUTUBE ============================

def _istemci(yol: Path) -> tuple[str, str]:
    j = json.loads(Path(yol).read_text(encoding="utf-8"))
    k = j.get("installed") or j.get("web") or {}
    if not k.get("client_id"):
        raise PaylasimHatasi("client_secret.json içinde client_id yok (Google Cloud'dan 'Masaüstü uygulaması' seç)")
    return k["client_id"], k["client_secret"]


def youtube_bagla(istemci_json: Path, jeton_yolu: Path) -> str:
    """Bir kerelik: tarayıcı açılır, YouTube kanalını seçip 'İzin ver' dersin. Yenileme anahtarı kaydedilir."""
    cid, sec = _istemci(istemci_json)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    donus = f"http://127.0.0.1:{port}"
    url = YT_YETKI + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": donus, "response_type": "code", "scope": YT_KAPSAM,
        "access_type": "offline", "prompt": "consent select_account"})
    gelen: dict = {}

    class Yakala(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            gelen.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Tamam! Bu pencereyi kapatabilirsin.</h2>".encode())

        def log_message(self, *a):
            pass

    sunucu = HTTPServer(("127.0.0.1", port), Yakala)
    print("Tarayıcı açılıyor. YouTube kanalını seç ve 'İzin ver' de...\nAçılmazsa bu adresi kopyala:\n" + url)
    webbrowser.open(url)
    while "code" not in gelen and "error" not in gelen:
        sunucu.handle_request()
    sunucu.server_close()
    if "error" in gelen:
        raise PaylasimHatasi(f"izin verilmedi: {gelen['error']}")
    j = _json(httpx.post(YT_JETON, data={"code": gelen["code"], "client_id": cid, "client_secret": sec,
                                         "redirect_uri": donus, "grant_type": "authorization_code"}, timeout=30))
    if not j.get("refresh_token"):
        raise PaylasimHatasi("Google yenileme anahtarı vermedi, tekrar dene")
    jeton_yolu.parent.mkdir(parents=True, exist_ok=True)
    jeton_yolu.write_text(json.dumps({"refresh_token": j["refresh_token"]}), encoding="utf-8")
    return "bağlandı"


class YouTube:
    def __init__(self, istemci_json: Path, jeton_yolu: Path, http: httpx.Client | None = None):
        self.istemci_json, self.jeton_yolu = Path(istemci_json), Path(jeton_yolu)
        self.http = http or httpx.Client(timeout=httpx.Timeout(300, connect=20))

    def bagli_mi(self) -> bool:
        return self.istemci_json.exists() and self.jeton_yolu.exists()

    def _erisim(self) -> str:
        cid, sec = _istemci(self.istemci_json)
        yenile = json.loads(self.jeton_yolu.read_text(encoding="utf-8"))["refresh_token"]
        return _json(self.http.post(YT_JETON, data={"client_id": cid, "client_secret": sec,
                                                    "refresh_token": yenile, "grant_type": "refresh_token"}))[
            "access_token"]

    def yukle(self, mp4: Path, baslik: str, aciklama: str, etiketler: list[str] | None = None) -> str:
        """Shorts olarak yükle, video linkini döndür."""
        erisim = self._erisim()
        veri = Path(mp4).read_bytes()
        govde = {"snippet": {"title": baslik[:100] or "GTA 6 #shorts", "description": aciklama[:4900],
                             "tags": [t.lstrip("#") for t in (etiketler or [])][:15], "categoryId": "20"},
                 "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
        r = self.http.post(YT_YUKLEME, params={"uploadType": "resumable", "part": "snippet,status"}, json=govde,
                           headers={"Authorization": f"Bearer {erisim}", "X-Upload-Content-Type": "video/mp4",
                                    "X-Upload-Content-Length": str(len(veri))})
        _json(r) if r.status_code >= 400 else None
        adres = r.headers.get("location") or r.headers.get("Location")
        if not adres:
            raise PaylasimHatasi("YouTube yükleme adresi vermedi")
        j = _json(self.http.put(adres, content=veri, headers={"Authorization": f"Bearer {erisim}",
                                                              "Content-Type": "video/mp4"}))
        return f"https://youtube.com/shorts/{j['id']}"


# ---- Telegram'dan bağlama: Google "cihaz kodu" yöntemi (telefonda google.com/device'a kodu yazarsın) ----
YT_CIHAZ = "https://oauth2.googleapis.com/device/code"
YT_CIHAZ_KAPSAM = "https://www.googleapis.com/auth/youtube"   # cihaz yönteminde izinli YouTube izni


def youtube_cihaz_baslat(istemci_json: Path, http: httpx.Client | None = None) -> dict:
    cid, _ = _istemci(istemci_json)
    h = http or httpx.Client(timeout=30)
    r = h.post(YT_CIHAZ, data={"client_id": cid, "scope": YT_CIHAZ_KAPSAM})
    if r.status_code >= 400:
        hata = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else ""
        if hata in ("invalid_client", "unauthorized_client"):
            raise PaylasimHatasi("Bu Google anahtar dosyası 'TV ve Sınırlı Giriş Cihazları' türünde değil. "
                                 "Google Cloud'da o türde yeni bir OAuth istemcisi oluşturup JSON'unu gönder.")
        _json(r)
    return r.json()


def youtube_cihaz_bekle(istemci_json: Path, cihaz: dict, jeton_yolu: Path, http: httpx.Client | None = None,
                        uyku=time.sleep) -> str:
    """Kullanıcı telefonda kodu girip izin verene kadar bekler (en fazla kodun süresi kadar)."""
    cid, sec = _istemci(istemci_json)
    h = http or httpx.Client(timeout=30)
    aralik = int(cihaz.get("interval", 5))
    bitis = time.time() + int(cihaz.get("expires_in", 1800))
    while time.time() < bitis:
        uyku(aralik)
        r = h.post(YT_JETON, data={"client_id": cid, "client_secret": sec, "device_code": cihaz["device_code"],
                                   "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        j = r.json()
        if j.get("refresh_token"):
            jeton_yolu.parent.mkdir(parents=True, exist_ok=True)
            jeton_yolu.write_text(json.dumps({"refresh_token": j["refresh_token"]}), encoding="utf-8")
            return "bağlandı"
        hata = j.get("error")
        if hata == "slow_down":
            aralik += 5
        elif hata not in ("authorization_pending", None):
            raise PaylasimHatasi(f"izin verilmedi: {hata}")
    raise PaylasimHatasi("kod süresi doldu, /bagla youtube ile tekrar dene")
