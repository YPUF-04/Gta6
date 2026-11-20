"""Kendini güncelleme: GitHub'daki son sürümü indirir, ayarlarına/kliplerine dokunmadan dosyaları yeniler.

Kullanım:  python -m klipci.guncelle            (yeni sürüm varsa günceller)
           python -m klipci.guncelle --zorla    (her durumda günceller)
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
DEPO = "YPUF-04/Gta6"
ZIP_URL = f"https://github.com/{DEPO}/archive/HEAD.zip"
SURUM_URL = f"https://raw.githubusercontent.com/{DEPO}/HEAD/klipci/__init__.py"
# bunlara asla dokunulmaz
KORUNAN_KLASOR = {".venv", "klipler", "ffmpeg", "logs", "modeller", ".git"}
KORUNAN_DOSYA = {"config.yaml", "durum.json", "klipci.pid"}


def _surum_sayi(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "0"))


def yerel_surum() -> str:
    m = re.search(r'SURUM\s*=\s*"([^"]+)"', (KOK / "klipci" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "0"


def uzak_surum(timeout: float = 15) -> str | None:
    import httpx
    try:
        r = httpx.get(SURUM_URL, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        m = re.search(r'SURUM\s*=\s*"([^"]+)"', r.text)
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None


def yeni_var_mi() -> tuple[bool, str, str | None]:
    yerel, uzak = yerel_surum(), uzak_surum()
    return (bool(uzak) and _surum_sayi(uzak) > _surum_sayi(yerel)), yerel, uzak


def _indir(url: str) -> bytes:
    import httpx
    parca = bytearray()
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        toplam = int(r.headers.get("content-length") or 0)
        for blok in r.iter_bytes(65536):
            parca += blok
            if toplam:
                print(f"\r  indiriliyor: %{len(parca) * 100 // toplam}  ", end="", flush=True)
            else:
                print(f"\r  indiriliyor: {len(parca) // 1024} KB  ", end="", flush=True)
    print()
    return bytes(parca)


def guncelle(atla: set[str] | None = None) -> int:
    """Dosyaları yeniler. Dönüş: yazılan dosya sayısı."""
    atla = {a.lower() for a in (atla or set())}
    veri = _indir(ZIP_URL)
    yazilan = 0
    with zipfile.ZipFile(io.BytesIO(veri)) as z:
        for ad in z.namelist():
            parcalar = ad.split("/", 1)
            if len(parcalar) < 2 or not parcalar[1] or ad.endswith("/"):
                continue
            goreli = Path(parcalar[1])
            if goreli.parts[0] in KORUNAN_KLASOR or goreli.name in KORUNAN_DOSYA or goreli.name.lower() in atla:
                continue
            hedef = KOK / goreli
            yeni = z.read(ad)
            try:
                if hedef.exists() and hedef.read_bytes() == yeni:
                    continue
            except OSError:
                pass
            hedef.parent.mkdir(parents=True, exist_ok=True)
            gecici = hedef.with_name(hedef.name + ".yeni")
            gecici.write_bytes(yeni)
            gecici.replace(hedef)
            yazilan += 1
    return yazilan


def paketleri_kur() -> None:
    gerek = KOK / "requirements.txt"
    if gerek.exists():
        print("  paketler kontrol ediliyor...", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                        "-r", str(gerek)], check=False)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    zorla = "--zorla" in sys.argv
    atla = {a.split("=", 1)[1] for a in sys.argv if a.startswith("--atla=")}
    var, yerel, uzak = yeni_var_mi()
    if uzak is None and not zorla:
        print(f"  Güncelleme kontrol edilemedi (internet?). Şu anki sürüm: {yerel}")
        return
    if not var and not zorla:
        print(f"  En güncel sürüm kurulu ✅ ({yerel})")
        return
    print(f"  Yeni sürüm bulundu: {yerel} → {uzak}. Güncelleniyor...", flush=True)
    try:
        n = guncelle(atla)
    except Exception as e:  # noqa: BLE001
        print(f"  Güncelleme indirilemedi: {e!r} — eski sürümle devam ediliyor.")
        return
    paketleri_kur()
    print(f"  Güncellendi ✅ ({n} dosya yenilendi) — sürüm {yerel_surum()}", flush=True)


if __name__ == "__main__":
    main()
