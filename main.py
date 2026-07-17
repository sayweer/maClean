"""maClean giriş noktası.

Tüm iş mantığı maclean/ paketindedir; bu dosya yalnızca genel görünüm
ayarlarını uygulayıp pencereyi açar ve teşhis için dosya loglamasını kurar.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import customtkinter as ctk

from maclean import __version__
from maclean.gui import App

LOG_DIR = Path.home() / "Library" / "Logs" / "maClean"
LOG_FILE = LOG_DIR / "maclean.log"


def _configure_logging() -> None:
    """Kök logger'a döner bir dosya handler'ı ekler (1 MB × 2 yedek).

    Yutulan istisnalar (worker hataları, entitlement çözümleme vb.) burada
    izlenebilir hale gelir. Dosya açılamazsa sessizce vazgeçilir — loglama
    uygulamanın çalışmasını asla engellemez.
    """

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
    except OSError:
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> None:
    _configure_logging()
    logging.getLogger(__name__).info("maClean %s başlatıldı", __version__)
    if "--smoke-test" in sys.argv:
        print(f"maClean {__version__}")
        return
    ctk.set_appearance_mode("System")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
