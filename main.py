"""maClean giriş noktası.

Tüm iş mantığı maclean/ paketindedir; bu dosya yalnızca genel görünüm
ayarlarını uygulayıp pencereyi açar.
"""

import customtkinter as ctk

from maclean.gui import App


def main() -> None:
    # Palet sıcak/açık tonlarda olduğundan sabit "Light" görünüm kullanılır.
    ctk.set_appearance_mode("Light")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
