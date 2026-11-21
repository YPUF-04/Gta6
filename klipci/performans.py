"""Paylaşılan videoların izlenme / beğeni istatistikleri ve bunlara göre öneri.

Her paylaşım kaydedilir; birkaç saatte bir Instagram ve YouTube'dan sayılar çekilir.
Her sabah 2. bota (paylaşım kanalı) günün istatistiği + "bundan sonra bunları paylaşacağız" önerisi gider.
Hangi yayıncının klipleri daha çok izleniyorsa sıradaki paylaşımlarda o öne alınır.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


def _k(n: float) -> str:
    n = int(n or 0)
    return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.1f}K" if n >= 1000 else str(n)


class Performans:
    def __init__(self, yol: Path):
        self.yol = yol
        self._kilit = threading.Lock()

    def _oku(self) -> dict:
        try:
            return json.loads(self.yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _yaz(self, d: dict) -> None:
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.yol.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.yol)

    def kaydet(self, hid: str, hesap: str, yayinci: str, kimlikler: dict) -> None:
        with self._kilit:
            d = self._oku()
            r = d.setdefault(hid, {"hesap": hesap, "yayinci": yayinci, "t": time.time(), "sayilar": {}})
            r.setdefault("kimlik", {}).update({k: v for k, v in kimlikler.items() if v})
            self._yaz(d)

    def guncelle(self, cek) -> int:
        """cek(platform, kimlik, hesap) -> {'izlenme', 'begeni', 'yorum', ...} | None. Son 7 günün paylaşımları."""
        d = self._oku()
        n = 0
        for hid, r in d.items():
            if time.time() - r.get("t", 0) > 7 * 86400:
                continue
            for plat, kimlik in (r.get("kimlik") or {}).items():
                try:
                    s = cek(plat, kimlik, r.get("hesap", ""))
                except Exception:  # noqa: BLE001
                    s = None
                if s:
                    r["sayilar"][plat] = s
                    n += 1
        with self._kilit:
            guncel = self._oku()
            for hid, r in d.items():
                if hid in guncel:
                    guncel[hid]["sayilar"] = r.get("sayilar", {})
            self._yaz(guncel)
        return n

    @staticmethod
    def _toplam(r: dict, alan: str) -> int:
        return sum(int((s or {}).get(alan, 0) or 0) for s in (r.get("sayilar") or {}).values())

    def yayinci_carpani(self, yayinci: str) -> float:
        """Bu yayıncının klipleri ortalamadan ne kadar çok izleniyor? (0.8 - 1.3; veri azsa 1)"""
        d = [r for r in self._oku().values() if r.get("sayilar")]
        if len(d) < 6:
            return 1.0
        genel = sum(self._toplam(r, "izlenme") for r in d) / len(d)
        bu = [self._toplam(r, "izlenme") for r in d if r.get("yayinci") == yayinci]
        if len(bu) < 2 or genel <= 0:
            return 1.0
        return max(0.8, min(1.3, (sum(bu) / len(bu)) / genel))

    def rapor(self, gun_sayisi: int = 7) -> str:
        d = [(hid, r) for hid, r in self._oku().items()
             if time.time() - r.get("t", 0) <= gun_sayisi * 86400 and r.get("sayilar")]
        if not d:
            return "📈 Henüz istatistik yok (paylaşımdan birkaç saat sonra gelir)."
        iz = sum(self._toplam(r, "izlenme") for _, r in d)
        bg = sum(self._toplam(r, "begeni") for _, r in d)
        yr = sum(self._toplam(r, "yorum") for _, r in d)
        satir = [f"📈 Son {gun_sayisi} gün: {len(d)} video · 👁 {_k(iz)} izlenme · ❤️ {_k(bg)} · 💬 {_k(yr)}"]
        for hesap in sorted({r.get("hesap", "") for _, r in d}):
            hd = [r for _, r in d if r.get("hesap") == hesap]
            satir.append(f"   [{hesap}] {len(hd)} video · 👁 {_k(sum(self._toplam(r, 'izlenme') for r in hd))}")
        en_iyi = sorted(d, key=lambda x: -self._toplam(x[1], "izlenme"))[:3]
        satir.append("\n🏆 En çok izlenenler")
        for i, (hid, r) in enumerate(en_iyi, 1):
            satir.append(f"{i}. {r.get('yayinci', '?')} [{r.get('hesap', '')}] — 👁 {_k(self._toplam(r, 'izlenme'))} "
                         f"❤️ {_k(self._toplam(r, 'begeni'))}")
        # yayıncı bazında ortalama → öneri
        yay: dict[str, list[int]] = {}
        for _, r in d:
            yay.setdefault(r.get("yayinci", "?"), []).append(self._toplam(r, "izlenme"))
        ort = {y: sum(v) / len(v) for y, v in yay.items()}
        genel = iz / len(d)
        iyi = [y for y, v in sorted(ort.items(), key=lambda x: -x[1]) if v >= genel * 1.2 and len(yay[y]) >= 2][:3]
        kotu = [y for y, v in sorted(ort.items(), key=lambda x: x[1]) if v <= genel * 0.6 and len(yay[y]) >= 2][:3]
        satir.append("\n🎯 Buna göre bundan sonra")
        if iyi:
            satir.append("✅ Daha çok paylaşacağız: " + ", ".join(f"{y} (ort. {_k(ort[y])})" for y in iyi))
        if kotu:
            satir.append("🔻 Daha az paylaşacağız: " + ", ".join(f"{y} (ort. {_k(ort[y])})" for y in kotu))
        if not iyi and not kotu:
            satir.append("Henüz belirgin fark yok, karışık paylaşmaya devam.")
        return "\n".join(satir)
