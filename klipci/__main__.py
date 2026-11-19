"""python -m klipci  -> programı başlatır."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

KOK = Path(__file__).resolve().parent.parent


def _ortam() -> None:
    # gereksiz uyarıları kapat, indirmeler sonsuza kadar takılmasın
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "20")
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    import warnings
    warnings.filterwarnings("ignore")


def uyumayi_engelle() -> None:
    """Program açıkken Windows uyku moduna geçmesin (ekran kapanabilir, bilgisayar uyumaz)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    _ortam()
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    (KOK / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)-8s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),
                  RotatingFileHandler(KOK / "logs" / "klipci.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")])
    for gurultu in ("httpx", "httpx2", "httpcore", "websockets", "streamlink", "faster_whisper",
                    "huggingface_hub", "urllib3", "anthropic"):
        logging.getLogger(gurultu).setLevel(logging.WARNING)

    cfg_yol = KOK / "config.yaml"
    if not cfg_yol.exists():
        raise SystemExit("config.yaml yok. Önce KURULUM.bat'ı çalıştır.")
    cfg = yaml.safe_load(cfg_yol.read_text(encoding="utf-8")) or {}

    (KOK / "klipci.pid").write_text(str(os.getpid()))
    uyumayi_engelle()
    from .uygulama import Uygulama
    try:
        asyncio.run(Uygulama(cfg, KOK).calistir())
    except KeyboardInterrupt:
        pass
    finally:
        (KOK / "klipci.pid").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
