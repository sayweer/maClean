"""customtkinter arayüzü: tarama akışı ve sonuçların gösterimi.

Threading kuralı: Tkinter tek thread'lidir. Tarama arka planda bir
threading.Thread'de çalışır; ilerleme/sonuç mesajları bir queue.Queue
üzerinden ana thread'e geçer ve widget'lar YALNIZCA ana thread'den (after
döngüsü içinde) güncellenir. Böylece büyük ~/Library taramalarında bile
arayüz donmaz.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import customtkinter as ctk

from . import scanner
from .models import MatchConfidence, OrphanItem, human_readable_size

# --- Renk paleti (colorhunt) ---------------------------------------------
CREAM = "#FBF5DD"       # ana arka plan
SAND = "#E7E1B1"        # ikincil yüzey, rozet
GREEN = "#306D29"       # ana vurgu / buton
DARK_GREEN = "#0D530E"  # hover / başlık / koyu metin
CARD = "#FFFDF5"        # sonuç kartı arka planı (sıcak beyaz)
TEXT = "#243325"        # gövde metni (koyu, okunur)
MUTED = "#6E7A63"       # ikincil / yol metni
HOME = str(Path.home())


def _short_path(path: Path, max_len: int = 64) -> str:
    """Yolu ~ ile kısaltıp gerekiyorsa ortadan keser."""
    text = str(path)
    if text.startswith(HOME):
        text = "~" + text[len(HOME):]
    if len(text) <= max_len:
        return text
    head = max_len // 2 - 2
    tail = max_len - head - 1
    return f"{text[:head]}…{text[-tail:]}"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("maClean")
        self.geometry("920x640")
        self.minsize(760, 520)
        self.configure(fg_color=CREAM)

        self.orphans: list[OrphanItem] = []
        self._queue: queue.Queue = queue.Queue()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_progress()
        self._build_results()
        self._show_empty_state()

    # -- Arayüz kurulumu ---------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header, text="maClean",
            font=ctk.CTkFont(size=30, weight="bold"), text_color=DARK_GREEN,
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = ctk.CTkLabel(
            header,
            text="Silinmiş uygulamaların geride bıraktığı dosyaları bulur.",
            font=ctk.CTkFont(size=13), text_color=MUTED,
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.scan_button = ctk.CTkButton(
            header, text="Taramayı Başlat", command=self._start_scan,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=GREEN, hover_color=DARK_GREEN, text_color="#FFFFFF",
            corner_radius=10, height=42, width=170,
        )
        self.scan_button.grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_progress(self) -> None:
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 4))
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(
            self.progress_frame, mode="indeterminate",
            progress_color=GREEN, fg_color=SAND, height=8, corner_radius=4,
        )
        self.status_label = ctk.CTkLabel(
            self.progress_frame, text="", font=ctk.CTkFont(size=12), text_color=MUTED,
        )
        # Başlangıçta gizli — tarama başlayınca gösterilir.
        self.progress_frame.grid_remove()

    def _build_results(self) -> None:
        self.results = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=14)
        self.results.grid(row=2, column=0, sticky="nsew", padx=28, pady=(8, 24))
        self.results.grid_columnconfigure(0, weight=1)

    # -- Durumlar ----------------------------------------------------------

    def _clear_results(self) -> None:
        for child in self.results.winfo_children():
            child.destroy()

    def _show_empty_state(self) -> None:
        self._clear_results()
        msg = ctk.CTkLabel(
            self.results,
            text="Başlamak için “Taramayı Başlat”a tıklayın.",
            font=ctk.CTkFont(size=15), text_color=MUTED,
        )
        msg.grid(row=0, column=0, pady=60)

    # -- Tarama akışı ------------------------------------------------------

    def _start_scan(self) -> None:
        self.scan_button.configure(state="disabled", text="Taranıyor…")
        self._clear_results()
        self.progress_frame.grid()
        self.progress.grid(row=0, column=0, sticky="ew")
        self.status_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.status_label.configure(text="Yüklü uygulamalar taranıyor…")
        self.progress.start()

        self._queue = queue.Queue()
        threading.Thread(target=self._scan_worker, daemon=True).start()
        self.after(100, self._poll_scan)

    def _scan_worker(self) -> None:
        """Arka plan thread'i — burada ASLA widget'a dokunulmaz."""
        try:
            installed_ids, name_by_id = scanner.discover_installed_apps()
            orphans = scanner.find_orphans(
                installed_ids,
                set(name_by_id.values()),
                progress_callback=lambda loc: self._queue.put(("progress", loc)),
            )
            self._queue.put(("done", orphans))
        except Exception as exc:  # noqa: BLE001 - hata UI'ye iletilir, çökme yok
            self._queue.put(("error", str(exc)))

    def _poll_scan(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    self.status_label.configure(text=f"Taranıyor: {payload}")
                elif kind == "done":
                    self._on_scan_done(payload)
                    return
                elif kind == "error":
                    self._on_scan_error(payload)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll_scan)

    def _finish_scan_ui(self) -> None:
        self.progress.stop()
        self.progress_frame.grid_remove()
        self.scan_button.configure(state="normal", text="Yeniden Tara")

    def _on_scan_error(self, message: str) -> None:
        self._finish_scan_ui()
        self._clear_results()
        ctk.CTkLabel(
            self.results, text=f"Tarama sırasında hata oluştu:\n{message}",
            font=ctk.CTkFont(size=14), text_color=DARK_GREEN,
        ).grid(row=0, column=0, pady=40, padx=20)

    def _on_scan_done(self, orphans: list[OrphanItem]) -> None:
        self.orphans = orphans
        self._finish_scan_ui()
        self._render_results()

    # -- Sonuç gösterimi ---------------------------------------------------

    def _render_results(self) -> None:
        self._clear_results()

        if not self.orphans:
            ctk.CTkLabel(
                self.results,
                text="Tebrikler! Öksüz kalıntı bulunamadı.",
                font=ctk.CTkFont(size=15, weight="bold"), text_color=GREEN,
            ).grid(row=0, column=0, pady=60)
            return

        high = [o for o in self.orphans if o.confidence is MatchConfidence.BUNDLE_ID]
        low = [o for o in self.orphans if o.confidence is MatchConfidence.NAME_FUZZY]

        row = 0
        if high:
            row = self._render_section(
                row, "Uygulama kalıntıları", high,
                "Silinmiş uygulamalara ait, kimliğiyle eşleşen kalıntılar.",
            )
        if low:
            row = self._render_section(
                row, "Dikkatli inceleyin", low,
                "İsim benzerliğine göre tahmin — hâlâ kullandığınız araçları "
                "içerebilir. Silmeden önce her birini kontrol edin.",
            )

    def _render_section(
        self, start_row: int, title: str, items: list[OrphanItem], note: str
    ) -> int:
        items = sorted(items, key=lambda o: o.size_bytes, reverse=True)
        total = human_readable_size(sum(o.size_bytes for o in items))

        header = ctk.CTkFrame(self.results, fg_color=SAND, corner_radius=8)
        header.grid(row=start_row, column=0, sticky="ew", padx=6, pady=(14, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text=f"{title}  ·  {len(items)} öğe  ·  {total}",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=DARK_GREEN,
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(8, 0))
        ctk.CTkLabel(
            header, text=note, font=ctk.CTkFont(size=11), text_color=MUTED,
            wraplength=780, justify="left",
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))

        next_row = start_row + 1
        for item in items:
            self._make_row(next_row, item)
            next_row += 1
        return next_row

    def _make_row(self, row: int, item: OrphanItem) -> None:
        frame = ctk.CTkFrame(self.results, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
        frame.grid_columnconfigure(0, weight=1)

        name = ctk.CTkLabel(
            frame, text=item.display_name,
            font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT, anchor="w",
        )
        name.grid(row=0, column=0, sticky="w", padx=(10, 8))

        badge = ctk.CTkLabel(
            frame, text=item.category.value,
            font=ctk.CTkFont(size=10), text_color=DARK_GREEN,
            fg_color=SAND, corner_radius=6, padx=8, pady=1,
        )
        badge.grid(row=0, column=1, padx=6)

        size = ctk.CTkLabel(
            frame, text=human_readable_size(item.size_bytes),
            font=ctk.CTkFont(size=13, weight="bold"), text_color=GREEN, width=90, anchor="e",
        )
        size.grid(row=0, column=2, sticky="e", padx=(6, 12))

        path = ctk.CTkLabel(
            frame, text=_short_path(item.path),
            font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w",
        )
        path.grid(row=1, column=0, columnspan=3, sticky="w", padx=(10, 12), pady=(0, 2))
