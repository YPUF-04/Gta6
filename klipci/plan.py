"""Stok + günlük paylaşım planı.

✅ bastığın klipler hesabın stoğuna girer (klipler/hazir/<HESAP>/).
Her gün, her hesap için en yüksek puanlı N klip seçilir ve günün farklı saatlerine dağıtılır
(saatler her gün değişir). Saati gelince Telegram'a gelir: video + Instagram / TikTok / YouTube
açıklamaları. Sen paylaşıp "✅ Paylaştım" basarsın.
"""
from __future__ import annotations

import json
import random
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

# İnsanların en çok baktığı saat aralıkları (Türkiye saati); her gün içlerinden rastgele dakika seçilir
PENCERELER = [(8, 9), (9, 10), (10, 11), (11, 12), (12, 13), (13, 14), (14, 15), (15, 16), (16, 17), (17, 18),
              (18, 19), (19, 20), (20, 21), (21, 22), (22, 23), (23, 24)]


def saatler_sec(adet: int, gun: date, simdi: datetime | None = None, tohum: str = "") -> list[str]:
    """Güne yayılmış, her gün farklı adet kadar saat (HH:MM). Bugünse geçmiş saatleri atla."""
    rnd = random.Random(f"{gun.isoformat()}-{tohum}")
    adet = max(1, min(adet, len(PENCERELER)))
    adim = len(PENCERELER) / adet
    secilen = []
    for i in range(adet):
        a, b = PENCERELER[min(len(PENCERELER) - 1, int(i * adim + rnd.random() * adim))]
        dk = rnd.randint(a * 60, b * 60 - 1)
        secilen.append(dk)
    secilen = sorted(set(secilen))
    if simdi and simdi.date() == gun:
        simdi_dk = simdi.hour * 60 + simdi.minute + 5
        secilen = [d for d in secilen if d >= simdi_dk]
    return [f"{d // 60:02d}:{d % 60:02d}" for d in secilen]


def aralikli_saatler(aralik_saat: float, gun: date, simdi: datetime | None = None, tohum: str = "",
                     bas: int = 9, bit: int = 24) -> list[str]:
    """Her X saatte bir (ör. 3 saat: ~09, ~12, ~15, ~18, ~21), her gün birkaç dakika kayan saatler."""
    rnd = random.Random(f"{gun.isoformat()}-{tohum}-aralik")
    adim = max(30, int(aralik_saat * 60))
    secilen = []
    for d in range(bas * 60, bit * 60, adim):
        secilen.append(min(bit * 60 - 1, max(bas * 60, d + rnd.randint(-15, 15))))
    if simdi and simdi.date() == gun:
        simdi_dk = simdi.hour * 60 + simdi.minute + 5
        secilen = [d for d in secilen if d >= simdi_dk]
    return [f"{d // 60:02d}:{d % 60:02d}" for d in sorted(set(secilen))]


def yayinci_adi(hid: str) -> str:
    """20261119_184652_kaicenat_TR -> kaicenat"""
    return hid.split("_", 2)[-1].rsplit("_", 1)[0]


def sirala_karisik(kl: list[Path]) -> list[Path]:
    """Aynı yayıncı art arda gelmeyecek şekilde sırala (mümkünse)."""
    kalan, out = list(kl), []
    while kalan:
        i = next((j for j, k in enumerate(kalan) if not out or yayinci_adi(k.name) != yayinci_adi(out[-1].name)), 0)
        out.append(kalan.pop(i))
    return out


class Planlayici:
    def __init__(self, klasor: Path):
        self.klasor = klasor
        self.yol = klasor / "plan.json"

    # ---------- dosya ----------
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

    # ---------- stok ----------
    def stok(self, hesap: str) -> list[tuple[Path, float]]:
        """Hesabın planlanmamış, paylaşılmamış klipleri (puana göre)."""
        planli = {it["hid"] for gun in self._oku().values() for lst in gun.values() for it in lst}
        out = []
        for k in (self.klasor / "hazir" / hesap).glob("*"):
            if k.is_dir() and k.name not in planli and list(k.glob("*.mp4")):
                try:
                    p = float(json.loads((k / "bilgi.json").read_text(encoding="utf-8")).get("puan", 0))
                except (OSError, ValueError):
                    p = 0.0
                out.append((k, p))
        out.sort(key=lambda x: -x[1])
        return out

    # ---------- plan ----------
    def plan_yap(self, gun: date, hesaplar: list[str], adet: int, simdi: datetime | None = None,
                 aralik_saat: float = 0) -> dict:
        d = self._oku()
        g = d.setdefault(gun.isoformat(), {})
        for h in hesaplar:
            mevcut = g.get(h, [])
            eksik = adet - len(mevcut)
            if eksik <= 0:
                continue
            tum = aralikli_saatler(aralik_saat, gun, simdi, h) if aralik_saat else saatler_sec(adet, gun, simdi, h)
            saatler = [s for s in tum if s not in {i["saat"] for i in mevcut}][:eksik]
            stok = self.stok(h)
            # puana göre seç ama aynı yayıncıdan günde en fazla yarısı olsun; aynı yayıncı arka arkaya gelmesin
            sinir = max(1, (adet + 1) // 2)
            sayac: dict[str, int] = {}
            secilen = []
            for k, _ in stok:
                y = yayinci_adi(k.name)
                if sayac.get(y, 0) < sinir:
                    secilen.append(k)
                    sayac[y] = sayac.get(y, 0) + 1
                if len(secilen) >= len(saatler):
                    break
            secilen = sirala_karisik(secilen)
            for saat, k in zip(saatler, secilen):
                mevcut.append({"hid": k.name, "saat": saat, "durum": "bekliyor"})
            g[h] = sorted(mevcut, key=lambda i: i["saat"])
        # 7 günden eski planları temizle
        for eski in [k for k in d if k < (gun - timedelta(days=7)).isoformat()]:
            del d[eski]
        self._yaz(d)
        return g

    def zamani_gelenler(self, simdi: datetime) -> list[tuple[str, dict]]:
        g = self._oku().get(simdi.date().isoformat(), {})
        su_an = simdi.strftime("%H:%M")
        return [(h, it) for h, lst in g.items() for it in lst if it["durum"] == "bekliyor" and it["saat"] <= su_an]

    def isaretle(self, hid: str, durum: str, gun: str | None = None) -> bool:
        d = self._oku()
        for g_ad, g in d.items():
            if gun and g_ad != gun:
                continue
            for lst in g.values():
                for it in lst:
                    if it["hid"] == hid:
                        it["durum"] = durum
                        self._yaz(d)
                        return True
        return False

    def ekle(self, gun: date, hesap: str, hid: str, saat: str, durum: str) -> None:
        """'Hemen paylaş' gibi plan dışı paylaşımlar da kayda girsin (stoktan düşsün, özete girsin)."""
        d = self._oku()
        lst = d.setdefault(gun.isoformat(), {}).setdefault(hesap, [])
        if not any(i["hid"] == hid for i in lst):
            lst.append({"hid": hid, "saat": saat, "durum": durum})
            lst.sort(key=lambda i: i["saat"])
            self._yaz(d)

    def platform_isaretle(self, hid: str, platform: str, deger: str) -> None:
        d = self._oku()
        for g in d.values():
            for lst in g.values():
                for it in lst:
                    if it["hid"] == hid:
                        it.setdefault("platformlar", {})[platform] = deger
                        self._yaz(d)
                        return

    def bul(self, hid: str) -> tuple[str, str, dict] | None:
        for g_ad, g in self._oku().items():
            for hesap, lst in g.items():
                for it in lst:
                    if it["hid"] == hid:
                        return g_ad, hesap, it
        return None

    def paylasildi(self, hesap: str, hid: str) -> None:
        self.isaretle(hid, "paylasildi")
        kaynak = self.klasor / "hazir" / hesap / hid
        if kaynak.exists():
            hedef = self.klasor / "paylasildi" / hesap / hid
            hedef.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(kaynak), str(hedef))

    def gun_plani(self, gun: date) -> dict:
        return self._oku().get(gun.isoformat(), {})
