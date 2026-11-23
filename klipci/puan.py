"""Klip puanlama + senin beğenilerinden öğrenme.

Her klibe 0-10 arası "izlenebilirlik" puanı verilir:
  chat patlaması, chat'teki gülme/şok tepkileri, sesteki ani yükselme (çığlık, patlama),
  görüntüdeki aksiyon, konuşma, yüz kamerası, (varsa) Claude'un viral puanı.
Sen ✅ / 🗑 bastıkça neyi sevdiğini öğrenir ve puanı sana göre ayarlar
(ör. "yüksek sesli + chat'in koptuğu klipleri seviyorsun", "kaicenat kliplerini onaylıyorsun").
"""
from __future__ import annotations

import json
import logging
import math
import subprocess
import threading
import time
from pathlib import Path

from .kayit import _PENCERESIZ, arac

log = logging.getLogger("puan")

OZELLIK_ADI = {
    "chat": "chat'in coşkusu",
    "tepki": "gülme/şok tepkileri",
    "ses": "ani bağırma/patlama sesi",
    "aksiyon": "hareketli sahne",
    "konusma": "konuşma",
    "yuz": "yüz kamerası",
    "yz": "yapay zekâ puanı",
}
TABAN_AGIRLIK = {"chat": 0.25, "tepki": 0.10, "ses": 0.20, "aksiyon": 0.15, "konusma": 0.10, "yuz": 0.05, "yz": 0.15}


def ses_ozellikleri(video: Path, baslangic: float, sure: float) -> dict:
    """Sesin yarım saniyelik dilimlerdeki şiddeti: en yüksek anlar normale göre ne kadar sıçrıyor?"""
    try:
        import numpy as np
        ham = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            capture_output=True, timeout=60, creationflags=_PENCERESIZ).stdout
        x = np.frombuffer(ham, np.int16).astype(np.float32) / 32768.0
        if len(x) < 8000:
            return {"ses": 0.0, "ses_db": -60.0}
        dilim = 4000
        rms = np.sqrt(np.array([np.mean(x[i:i + dilim] ** 2) for i in range(0, len(x) - dilim + 1, dilim)]) + 1e-10)
        db = 20 * np.log10(rms)
        sicrama = float(np.percentile(db, 95) - np.median(db))
        return {"ses": max(0.0, min(1.0, sicrama / 18.0)), "ses_db": float(np.max(db))}
    except Exception as e:  # noqa: BLE001
        log.debug("ses analizi olmadı: %s", e)
        return {"ses": 0.0, "ses_db": -60.0}


def an_tepkisi(video: Path, baslangic: float, sure: float, an: float) -> float:
    """Patlama anı çevresinde ses ne kadar yükseldi (dB, klibin normaline göre)? Yayıncı bağırdı/güldü mü?"""
    try:
        import numpy as np
        ham = subprocess.run(
            [arac("ffmpeg"), "-v", "error", "-ss", f"{baslangic:.2f}", "-t", f"{sure:.2f}", "-i", str(video),
             "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            capture_output=True, timeout=60, creationflags=_PENCERESIZ).stdout
        x = np.frombuffer(ham, np.int16).astype(np.float32) / 32768.0
        d = 4000   # yarım saniye
        if len(x) < d * 4:
            return 0.0
        db = 20 * np.log10(np.sqrt(np.array([np.mean(x[i:i + d] ** 2) for i in range(0, len(x) - d + 1, d)])) + 1e-10)
        a, b = max(0, int((an - 8) * 2)), min(len(db), int((an + 5) * 2) + 1)
        if b <= a:
            return 0.0
        return float(np.max(db[a:b]) - np.median(db))
    except Exception as e:  # noqa: BLE001
        log.debug("an tepkisi ölçülemedi: %s", e)
        return 0.0


def ozellik_cikar(chat_kat: float, chat: list[tuple[float, str, str]], sure: float, ses: dict,
                  aksiyon: float, kelime_sayisi: int, facecam: bool, yz_puan: float | None) -> dict:
    from .spike import mesaj_puani
    tepki = sum(1 for _, _, m in chat if mesaj_puani(m)[0] > 1)
    return {
        "chat": max(0.0, min(1.0, (chat_kat - 1) / 6)),
        "tepki": min(1.0, tepki / max(1, len(chat)) * 1.5) if chat else 0.0,
        "ses": ses.get("ses", 0.0),
        "aksiyon": max(0.0, min(1.0, aksiyon)),
        "konusma": min(1.0, kelime_sayisi / max(1.0, sure * 2.2)),
        "yuz": 1.0 if facecam else 0.0,
        "yz": (yz_puan / 10.0) if yz_puan is not None else 0.5,
    }


def taban_puan(oz: dict) -> float:
    return round(10 * sum(TABAN_AGIRLIK[k] * oz.get(k, 0.0) for k in TABAN_AGIRLIK), 1)


class Ogrenci:
    """Puan geçmişi + kararların (✅/🗑) üzerinden kişisel tercih modeli."""

    def __init__(self, yol: Path):
        self.yol = yol
        self._kilit = threading.Lock()
        self.kayitlar: dict[str, dict] = {}
        try:
            for satir in yol.read_text(encoding="utf-8").splitlines():
                if satir.strip():
                    r = json.loads(satir)
                    self.kayitlar[r["id"]] = r
        except (OSError, ValueError):
            pass
        self.w: dict[str, float] = {}
        self.b = 0.0
        self._egit()

    def _yaz(self) -> None:
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.yol.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.kayitlar.values()),
                       encoding="utf-8")
        tmp.replace(self.yol)

    @staticmethod
    def _etiket(r: dict) -> str | None:
        """Senin kararın (👍/👎) önce gelir; yoksa izlenme sonucu (çok izlendi = iyi, az izlendi = kötü)."""
        if r.get("karar") in ("onay", "sil"):
            return r["karar"]
        return {"iyi": "onay", "kotu": "sil"}.get(r.get("izlenme"))

    def kararlilar(self) -> list[dict]:
        return [r for r in self.kayitlar.values() if self._etiket(r)]

    def izlenme_isaretle(self, sonuc: dict[str, str]) -> int:
        """{hid: 'iyi'|'kotu'} — paylaşılan kliplerin izlenme sonucunu öğrenmeye ekle."""
        n = 0
        with self._kilit:
            for hid, e in sonuc.items():
                r = self.kayitlar.get(hid)
                if r and r.get("izlenme") != e:
                    r["izlenme"] = e
                    n += 1
            if n:
                self._yaz()
        if n:
            self._egit()
        return n

    def _egit(self) -> None:
        """Basit lojistik regresyon (numpy yok sayılırsa saf Python)."""
        veri = self.kararlilar()
        if len(veri) < 6 or len({self._etiket(r) for r in veri}) < 2:
            self.w, self.b = {}, 0.0
            return
        anahtar = list(TABAN_AGIRLIK)
        w = {k: 0.0 for k in anahtar}
        b = 0.0
        for _ in range(400):
            gw = {k: 0.0 for k in anahtar}
            gb = 0.0
            for r in veri:
                x = r["oz"]
                y = 1.0 if self._etiket(r) == "onay" else 0.0
                a = 3.0 if r.get("bayildi") else 1.0          # 😍 bayıldım = 3 kat güçlü sinyal
                p = 1 / (1 + math.exp(-(b + sum(w[k] * x.get(k, 0) for k in anahtar))))
                for k in anahtar:
                    gw[k] += a * (p - y) * x.get(k, 0)
                gb += a * (p - y)
            n = sum(3.0 if r.get("bayildi") else 1.0 for r in veri)
            for k in anahtar:
                w[k] -= 0.5 * (gw[k] / n + 0.01 * w[k])
            b -= 0.5 * gb / n
        self.w, self.b = w, b

    def _kanal_orani(self, kanal: str) -> tuple[float, int]:
        k = [r for r in self.kararlilar() if r.get("kanal") == kanal]
        onay = sum(1 for r in k if r["karar"] == "onay")
        return (onay + 1) / (len(k) + 2), len(k)

    def puanla(self, kid: str, kanal: str, oz: dict) -> tuple[float, str]:
        """(0-10 puan, Türkçe açıklama)"""
        taban = taban_puan(oz)
        neden = []
        puan = taban
        if self.w:
            z = self.b + sum(self.w[k] * oz.get(k, 0) for k in self.w)
            p = 1 / (1 + math.exp(-z))
            oran, n = self._kanal_orani(kanal)
            if n >= 3:
                p = 0.7 * p + 0.3 * oran
            puan = round(0.4 * taban + 0.6 * 10 * p, 1)
            katki = sorted(((self.w[k] * oz.get(k, 0), k) for k in self.w), reverse=True)
            sevdigi = [OZELLIK_ADI[k] for c, k in katki[:2] if c > 0.15]
            if sevdigi:
                neden.append("sevdiğin tarz: " + " + ".join(sevdigi))
            if n >= 3:
                neden.append(f"{kanal} kliplerinin %{int(oran * 100)}'ini beğendin")
        else:
            kalan = max(0, 6 - len(self.kararlilar()))
            neden.append(f"{kalan} karar daha verince senin zevkine göre puanlamaya başlayacağım" if kalan
                         else "beğenilerinden öğrenmek için hem ✅ hem 🗑 kullan")

        with self._kilit:
            self.kayitlar[kid] = {"id": kid, "kanal": kanal, "oz": oz, "taban": taban, "puan": puan,
                                  "karar": None, "t": time.time()}
            self._yaz()
        return puan, " · ".join(neden)

    def sira(self, kid: str, saat: float = 24) -> tuple[int, int]:
        """Son 24 saatteki klipler arasında kaçıncı (1 = en iyi)."""
        sinir = time.time() - saat * 3600
        son = [r for r in self.kayitlar.values() if r.get("t", 0) >= sinir]
        son.sort(key=lambda r: -r.get("puan", 0))
        for i, r in enumerate(son, 1):
            if r["id"] == kid:
                return i, len(son)
        return 0, len(son)

    def bayildi(self, kid: str) -> list[str]:
        """😍: en güçlü olumlu sinyal. Bu klibi öne çıkaran özellikleri (Türkçe adlarıyla) döndürür."""
        with self._kilit:
            r = self.kayitlar.get(kid)
            if not r:
                return []
            r["karar"], r["bayildi"] = "onay", True
            self._yaz()
        self._egit()
        oz = r.get("oz") or {}
        guclu = [k for k, v in sorted(oz.items(), key=lambda x: -x[1]) if k != "yz" and v >= 0.45][:3]
        return [OZELLIK_ADI.get(k, k) for k in guclu]

    def bayildiklari(self) -> list[dict]:
        return [r for r in self.kayitlar.values() if r.get("bayildi")]

    def karar(self, kid: str, karar: str) -> None:
        with self._kilit:
            r = self.kayitlar.get(kid)
            if not r:
                return
            r["karar"] = karar
            self._yaz()
        self._egit()

    def ozet(self) -> str:
        veri = self.kararlilar()
        if not veri:
            return "Henüz hiç ✅ / 🗑 kararı yok. Kliplere karar verdikçe zevkini öğreneceğim."
        onay = sum(1 for r in veri if r["karar"] == "onay")
        satir = [f"📊 {len(veri)} karar: {onay} ✅, {len(veri) - onay} 🗑"]
        kanallar: dict[str, list[int]] = {}
        for r in veri:
            kanallar.setdefault(r["kanal"], [0, 0])
            kanallar[r["kanal"]][0 if r["karar"] == "onay" else 1] += 1
        en = sorted(kanallar.items(), key=lambda x: (-(x[1][0] + 1) / (sum(x[1]) + 2), -sum(x[1])))[:5]
        satir.append("En çok beğendiğin yayıncılar: " + ", ".join(f"{k} ({o}✅/{s}🗑)" for k, (o, s) in en))
        if self.w:
            sirali = sorted(self.w.items(), key=lambda x: -x[1])
            satir.append("Sevdiğin: " + ", ".join(OZELLIK_ADI[k] for k, v in sirali[:3] if v > 0))
            sevmedigi = [OZELLIK_ADI[k] for k, v in sirali[::-1][:2] if v < 0]
            if sevmedigi:
                satir.append("Pek sevmediğin: " + ", ".join(sevmedigi))
        else:
            satir.append("Zevkini öğrenmem için en az 8 karar (hem ✅ hem 🗑) lazım.")
        return "\n".join(satir)
