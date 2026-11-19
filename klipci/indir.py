"""KURULUM.bat: altyazı modelini ve yüz modelini önceden indirir (yüzdelik ilerleme gösterir)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

KOK = Path(__file__).resolve().parent.parent


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
    import warnings
    warnings.filterwarnings("ignore")

    from .yuz import model_indir
    print("  Yüz bulma modeli...", "tamam ✅" if model_indir() else "indirilemedi (yedek yöntem kullanılacak)", flush=True)

    model = "small"
    try:
        cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8")) or {}
        model = (cfg.get("altyazi") or {}).get("whisper_model", "small")
    except Exception:  # noqa: BLE001
        pass
    try:
        from huggingface_hub import snapshot_download
    except Exception:  # noqa: BLE001
        print("  Altyazı paketi kurulu değil, model indirme atlandı.")
        return
    print(f"  Altyazı modeli ({model}, ~500 MB) indiriliyor — aşağıdaki çubuk yüzdeyi gösterir:", flush=True)
    for deneme in range(3):
        try:
            snapshot_download(f"Systran/faster-whisper-{model}")
            print("  Altyazı modeli tamam ✅", flush=True)
            return
        except Exception as e:  # noqa: BLE001
            print(f"  İndirme kesildi ({e!r}), tekrar deneniyor ({deneme + 2}/3)...", flush=True)
    print("  Altyazı modeli indirilemedi. Sorun değil: program açılınca tekrar dener.")


if __name__ == "__main__":
    main()
