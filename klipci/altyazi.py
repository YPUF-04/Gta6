"""Konuşmayı yazıya çevir (faster-whisper, bilgisayarında ücretsiz çalışır)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("altyazi")


@dataclass
class Kelime:
    bas: float
    bit: float
    metin: str


@dataclass
class Cozum:
    dil: str
    segmentler: list[tuple[float, float, str]]
    kelimeler: list[Kelime]
    guven: float = 0.0   # dilden ne kadar emin

    @property
    def metin(self) -> str:
        return " ".join(s[2] for s in self.segmentler).strip()


def _nvidia_dll_yollari() -> None:
    """Windows'ta pip ile kurulan NVIDIA kütüphanelerini (cuBLAS/cuDNN) bulunur hale getir."""
    import os
    import sys
    if os.name != "nt":
        return
    for kok in sys.path:
        nv = Path(kok) / "nvidia"
        if nv.is_dir():
            for bin_ in nv.glob("*/bin"):
                try:
                    os.add_dll_directory(str(bin_))
                    os.environ["PATH"] = str(bin_) + os.pathsep + os.environ.get("PATH", "")
                except OSError:
                    pass


class Yaziya:
    def __init__(self, model: str = "small", cihaz: str = "auto"):
        self.model_adi, self.cihaz = model, cihaz
        self._model = None
        self._kilit = threading.Lock()   # birden çok kurgu işçisi aynı modeli paylaşır
        self.durum = "hazırlanıyor (ilk açılışta model indiriliyor, birkaç dk)"

    def _yukle(self):
        with self._kilit:
            return self._yukle_kilitli()

    def _dene(self, cihaz: str):
        from faster_whisper import WhisperModel
        tip = "float16" if cihaz == "cuda" else "int8"
        m = WhisperModel(self.model_adi, device=cihaz, compute_type=tip)
        if cihaz == "cuda":   # ekran kartı gerçekten çalışıyor mu? (eksik DLL burada patlar)
            import numpy as np
            list(m.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])
        return m

    def _yukle_kilitli(self):
        if self._model is not None:
            return self._model
        cihaz = self.cihaz
        if cihaz in ("auto", "cuda"):
            _nvidia_dll_yollari()
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() == 0:
                    cihaz = "cpu"
                else:
                    cihaz = "cuda"
            except Exception:  # noqa: BLE001
                cihaz = "cpu"
        log.info("altyazı modeli yükleniyor (%s, %s) — ilk sefer ~500 MB indirir", self.model_adi, cihaz)
        if cihaz == "cuda":
            # ekran kartı varsa daha iyi model: Türkçeyi çok daha doğru yazar, yine de hızlı
            if self.model_adi in ("auto", "small", "base", "tiny"):
                eski, self.model_adi = self.model_adi, "large-v3-turbo"
                try:
                    self._model = self._dene("cuda")
                    self.durum = "hazır (ekran kartı, büyük model)"
                    log.info("altyazı modeli hazır (ekran kartı, large-v3-turbo)")
                    return self._model
                except Exception as e:  # noqa: BLE001
                    log.warning("büyük model olmadı (%r), %s deneniyor", e, eski)
                    self.model_adi = "small" if eski == "auto" else eski
            try:
                self._model = self._dene("cuda")
                self.durum = "hazır (ekran kartı)"
                log.info("altyazı modeli hazır (ekran kartı ile, hızlı)")
                return self._model
            except Exception as e:  # noqa: BLE001
                log.warning("ekran kartıyla olmadı (%r), işlemciyle devam", e)
        if self.model_adi == "auto":
            self.model_adi = "small"
        self._model = self._dene("cpu")
        self.durum = "hazır (işlemci)"
        log.info("altyazı modeli hazır (işlemci ile)")
        return self._model

    def onyukle(self, deneme: int = 0) -> bool:
        """Program açılınca arka planda modeli hazırla (ilk klip beklemesin). İnternet yoksa sonra tekrar."""
        try:
            self._yukle()
            return True
        except Exception as e:  # noqa: BLE001
            self.durum = f"hazırlanamadı: {e!r}"[:200]
            log.warning("altyazı modeli şimdilik hazırlanamadı (%r) — sonra tekrar denenecek", e)
            return False

    def coz(self, wav: Path, dil: str = "") -> Cozum | None:
        """dil: yayının dili biliniyorsa ("tr"/"en") verilir — oyun sesi varken dili tahmin etmek zor."""
        try:
            m = self._yukle()
        except Exception as e:  # noqa: BLE001
            log.warning("altyazı modeli kullanılamıyor: %r", e)
            self.durum = f"hazırlanamadı: {e!r}"[:200]
            raise RuntimeError(f"altyazı modeli yüklenemedi: {e!r}"[:200]) from e
        ayar = dict(word_timestamps=True, beam_size=5, condition_on_previous_text=False,
                    vad_filter=True, vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 400})
        # önce dili kendisi anlasın (yayıncı dilini yanlış seçmiş olabilir); emin değilse yayının dilini kullan
        segs, info = m.transcribe(str(wav), **ayar)
        if dil in ("tr", "en") and getattr(info, "language_probability", 1.0) < 0.6 and info.language != dil:
            segs, info = m.transcribe(str(wav), language=dil, **ayar)
        segler, kelimeler = [], []
        for s in segs:
            if not gercek_konusma_mi(s.text, getattr(s, "no_speech_prob", 0.0), getattr(s, "avg_logprob", 0.0)):
                continue
            segler.append((s.start, s.end, s.text.strip()))
            for w in (s.words or []):
                kelimeler.append(Kelime(w.start, w.end, w.word.strip()))
        return Cozum(info.language, segler, kelimeler, float(getattr(info, "language_probability", 0.0)))


# Whisper müzik/oyun sesinde bazen olmayan cümleler uydurur; bunlar altyazıya girmesin
_UYDURMA = ("thank you for watching", "thanks for watching", "subscribe", "altyazı m.k", "altyazı:",
            "izlediğiniz için teşekkür", "abone ol", "www.", ".com", "♪")


def gercek_konusma_mi(metin: str, sessizlik: float, guven: float) -> bool:
    t = (metin or "").strip().lower()
    if not t:
        return False
    if any(u in t for u in _UYDURMA):
        return False
    if sessizlik > 0.6 and guven < -0.8:   # büyük ihtimalle konuşma yok, sadece ses
        return False
    return True


def tr_buyuk(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def kelime_parcala(kelimeler: list[Kelime], en_cok_kelime: int = 3, en_uzun_sn: float = 1.4):
    """Kelimeleri viral klip tarzı 2-3 kelimelik hızlı altyazılara böl.

    Dönüş: (başlangıç, bitiş, metin, [(kelime_bas, kelime_bit, kelime), ...]) — kelime kelime vurgu için."""
    out, grup = [], []

    def ekle(g):
        out.append([g[0].bas, g[-1].bit, " ".join(x.metin for x in g), [(x.bas, x.bit, x.metin) for x in g]])

    for k in kelimeler:
        if not k.metin:
            continue
        if grup and (len(grup) >= en_cok_kelime or k.bit - grup[0].bas > en_uzun_sn
                     or k.bas - grup[-1].bit > 0.6):
            ekle(grup)
            grup = []
        grup.append(k)
    if grup:
        ekle(grup)
    # boşlukları kapat ki altyazı titremesin
    for i in range(len(out) - 1):
        if out[i + 1][0] - out[i][1] < 0.3:
            out[i][1] = out[i + 1][0]
    return [tuple(x) for x in out]


def segment_parcala(segler: list[tuple[float, float, str]], en_cok_kelime: int = 3):
    """Çevrilmiş cümleleri (kelime zamanı yok) süreye orantılı parçalara böl."""
    out = []
    for b, e, t in segler:
        kel = t.split()
        if not kel:
            continue
        parca = [kel[i:i + en_cok_kelime] for i in range(0, len(kel), en_cok_kelime)]
        adim = (e - b) / len(parca)
        for i, p in enumerate(parca):
            out.append((b + i * adim, b + (i + 1) * adim, " ".join(p)))
    return out
