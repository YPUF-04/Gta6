"""Konuşmayı yazıya çevir (faster-whisper, bilgisayarında ücretsiz çalışır)."""
from __future__ import annotations

import logging
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

    @property
    def metin(self) -> str:
        return " ".join(s[2] for s in self.segmentler).strip()


class Yaziya:
    def __init__(self, model: str = "small", cihaz: str = "auto"):
        self.model_adi, self.cihaz = model, cihaz
        self._model = None

    def _yukle(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            cihaz = self.cihaz
            if cihaz == "auto":
                try:
                    import ctranslate2
                    cihaz = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
                except Exception:  # noqa: BLE001
                    cihaz = "cpu"
            tip = "float16" if cihaz == "cuda" else "int8"
            log.info("whisper modeli yükleniyor (%s, %s) — ilk sefer indirir, biraz sürer", self.model_adi, cihaz)
            self._model = WhisperModel(self.model_adi, device=cihaz, compute_type=tip)
        return self._model

    def coz(self, wav: Path) -> Cozum | None:
        try:
            m = self._yukle()
        except Exception as e:  # noqa: BLE001
            log.warning("whisper kullanılamıyor: %s", e)
            return None
        segs, info = m.transcribe(str(wav), word_timestamps=True, vad_filter=True)
        segler, kelimeler = [], []
        for s in segs:
            segler.append((s.start, s.end, s.text.strip()))
            for w in (s.words or []):
                kelimeler.append(Kelime(w.start, w.end, w.word.strip()))
        return Cozum(info.language, segler, kelimeler)


def tr_buyuk(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def kelime_parcala(kelimeler: list[Kelime], en_cok_kelime: int = 3, en_uzun_sn: float = 1.4):
    """Kelimeleri viral klip tarzı 2-3 kelimelik hızlı altyazılara böl."""
    out, grup = [], []
    for k in kelimeler:
        if not k.metin:
            continue
        if grup and (len(grup) >= en_cok_kelime or k.bit - grup[0].bas > en_uzun_sn
                     or k.bas - grup[-1].bit > 0.6):
            out.append((grup[0].bas, grup[-1].bit, " ".join(g.metin for g in grup)))
            grup = []
        grup.append(k)
    if grup:
        out.append((grup[0].bas, grup[-1].bit, " ".join(g.metin for g in grup)))
    # boşlukları kapat ki altyazı titremesin
    duz = []
    for i, (b, e, t) in enumerate(out):
        if i + 1 < len(out) and out[i + 1][0] - e < 0.3:
            e = out[i + 1][0]
        duz.append((b, e, t))
    return duz


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
