"""YOUTUBE_BAGLA.bat bunu çalıştırır: bir hesabın (TR / EN) YouTube kanalını bir kez bağlar."""
from __future__ import annotations

import sys
from pathlib import Path

from .paylas import youtube_bagla

KOK = Path(__file__).resolve().parent.parent


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    hesap = (sys.argv[1] if len(sys.argv) > 1 else input("Hangi hesap? (TR ya da EN yaz): ")).strip().upper()
    if not hesap:
        sys.exit(1)
    istemci = KOK / "youtube" / f"client_secret_{hesap}.json"
    if not istemci.exists():
        istemci = KOK / "youtube" / "client_secret.json"
    if not istemci.exists():
        print(f"\nHATA: {istemci} bulunamadı.\n"
              "Google Cloud'dan indirdiğin dosyanın adını client_secret.json yap ve programın klasöründeki\n"
              "'youtube' klasörüne koy (klasör yoksa oluştur). README'deki YOUTUBE adımlarına bak.")
        sys.exit(1)
    print(f"\n{hesap} hesabı için YouTube kanalı bağlanıyor...")
    try:
        youtube_bagla(istemci, KOK / "youtube" / f"{hesap}.json")
    except Exception as e:  # noqa: BLE001
        print(f"\nOlmadı: {e}")
        sys.exit(1)
    print(f"\n✅ {hesap} hesabının YouTube kanalı bağlandı. Program paylaşım saatinde kendisi yükleyecek.")


if __name__ == "__main__":
    main()
