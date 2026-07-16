"""maClean giriş noktası.

Tüm iş mantığı maclean/ paketindedir; bu dosya yalnızca genel görünüm
ayarlarını uygulayıp pencereyi açar.
"""

import sys

import customtkinter as ctk

from maclean import __version__
from maclean.gui import App


def main() -> None:
    if "--smoke-test" in sys.argv:
        print(f"maClean {__version__}")
        return
    ctk.set_appearance_mode("System")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
