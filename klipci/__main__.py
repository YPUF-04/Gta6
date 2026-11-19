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


def main() -> None:
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
    for gurultu in ("httpx", "websockets", "streamlink", "faster_whisper"):
        logging.getLogger(gurultu).setLevel(logging.WARNING)

    cfg_yol = KOK / "config.yaml"
    if not cfg_yol.exists():
        raise SystemExit("config.yaml yok. Önce KURULUM.bat'ı çalıştır.")
    cfg = yaml.safe_load(cfg_yol.read_text(encoding="utf-8")) or {}

    (KOK / "klipci.pid").write_text(str(os.getpid()))
    from .uygulama import Uygulama
    try:
        asyncio.run(Uygulama(cfg, KOK).calistir())
    except KeyboardInterrupt:
        pass
    finally:
        (KOK / "klipci.pid").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
