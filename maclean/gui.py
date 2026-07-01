"""customtkinter arayüzü: tarama, seçim ve Çöp'e taşıma akışı.

Threading kuralı: Tkinter tek thread'lidir. Uzun süren işler (tarama ve Çöp'e
taşıma) arka planda bir threading.Thread'de çalışır; mesajlar bir queue.Queue
üzerinden ana thread'e geçer ve widget'lar YALNIZCA ana thread'den (after
döngüsü içinde) güncellenir. Böylece arayüz donmaz.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import customtkinter as ctk

from . import scanner, trash
from .models import MatchConfidence, OrphanItem, human_readable_size

# --- Renk paleti (colorhunt) ---------------------------------------------
CREAM = "#FBF5DD"       # ana arka plan
SAND = "#E7E1B1"        # ikincil yüzey, rozet
GREEN = "#306D29"       # ana vurgu / buton
DARK_GREEN = "#0D530E"  # hover / başlık / temizleme aksiyonu
CARD = "#FFFDF5"        # sonuç kartı arka planı (sıcak beyaz)
TEXT = "#243325"        # gövde metni (koyu, okunur)
MUTED = "#6E7A63"       # ikincil / yol metni
TERRA = "#B5502E"       # kiremit — uyarı / yıkıcı aksiyon
TERRA_DARK = "#93401F"  # kiremit hover
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
        self.geometry("920x680")
        self.minsize(760, 560)
        self.configure(fg_color=CREAM)

        self.orphans: list[OrphanItem] = []
        self._checkboxes: dict[int, ctk.CTkCheckBox] = {}
        self._queue: queue.Queue = queue.Queue()
        self._banner: str | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_progress()
        self._build_results()
        self._build_footer()
        self._show_empty_state()

    # -- Arayüz kurulumu ---------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="maClean",
            font=ctk.CTkFont(size=30, weight="bold"), text_color=DARK_GREEN,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header, text="Silinmiş uygulamaların geride bıraktığı dosyaları bulur.",
            font=ctk.CTkFont(size=13), text_color=MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

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
        self.progress_frame.grid_remove()

    def _build_results(self) -> None:
        self.results = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=14)
        self.results.grid(row=2, column=0, sticky="nsew", padx=28, pady=(8, 4))
        self.results.grid_columnconfigure(0, weight=1)

    def _build_footer(self) -> None:
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.grid(row=3, column=0, sticky="ew", padx=28, pady=(4, 22))
        self.footer.grid_columnconfigure(0, weight=1)

        self.summary_label = ctk.CTkLabel(
            self.footer, text="", font=ctk.CTkFont(size=13), text_color=TEXT, anchor="w",
        )
        self.summary_label.grid(row=0, column=0, sticky="w")

        self.trash_button = ctk.CTkButton(
            self.footer, text="Seçilenleri Çöp'e Taşı", command=self._confirm_and_trash,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=TERRA, hover_color=TERRA_DARK, text_color="#FFFFFF",
            corner_radius=10, height=42, width=210, state="disabled",
        )
        self.trash_button.grid(row=0, column=1, sticky="e")
        self.footer.grid_remove()  # sonuç gelene kadar gizli

    # -- Durumlar ----------------------------------------------------------

    def _clear_results(self) -> None:
        for child in self.results.winfo_children():
            child.destroy()
        self._checkboxes.clear()

    def _show_empty_state(self) -> None:
        self._clear_results()
        self.footer.grid_remove()
        ctk.CTkLabel(
            self.results, text="Başlamak için “Taramayı Başlat”a tıklayın.",
            font=ctk.CTkFont(size=15), text_color=MUTED,
        ).grid(row=0, column=0, pady=60)

    # -- Tarama akışı ------------------------------------------------------

    def _start_scan(self) -> None:
        self.scan_button.configure(state="disabled", text="Taranıyor…")
        self.trash_button.configure(state="disabled")
        self._banner = None
        self._clear_results()
        self.footer.grid_remove()
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
                installed_ids, set(name_by_id.values()),
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
        row = 0

        if self._banner:
            banner = ctk.CTkFrame(self.results, fg_color=SAND, corner_radius=8)
            banner.grid(row=row, column=0, sticky="ew", padx=6, pady=(8, 4))
            banner.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                banner, text=self._banner, font=ctk.CTkFont(size=13, weight="bold"),
                text_color=DARK_GREEN, wraplength=800, justify="left",
            ).grid(row=0, column=0, sticky="w", padx=14, pady=8)
            row += 1

        if not self.orphans:
            self.footer.grid_remove()
            ctk.CTkLabel(
                self.results,
                text="Öksüz kalıntı bulunamadı." if self._banner
                else "Tebrikler! Öksüz kalıntı bulunamadı.",
                font=ctk.CTkFont(size=15, weight="bold"), text_color=GREEN,
            ).grid(row=row, column=0, pady=50)
            return

        high = [o for o in self.orphans if o.confidence is MatchConfidence.BUNDLE_ID]
        low = [o for o in self.orphans if o.confidence is MatchConfidence.NAME_FUZZY]

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
                note_color=TERRA,
            )

        self.footer.grid()
        self._update_summary()

    def _render_section(
        self, start_row: int, title: str, items: list[OrphanItem], note: str,
        note_color: str = MUTED,
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
            header, text=note, font=ctk.CTkFont(size=11), text_color=note_color,
            wraplength=640, justify="left",
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e", padx=12)
        ctk.CTkButton(
            actions, text="Tümünü seç", width=90, height=26,
            font=ctk.CTkFont(size=11), fg_color="transparent", text_color=DARK_GREEN,
            hover_color=CREAM, command=lambda it=items: self._select_all(it, True),
        ).grid(row=0, column=0, padx=(0, 4))
        ctk.CTkButton(
            actions, text="Temizle", width=70, height=26,
            font=ctk.CTkFont(size=11), fg_color="transparent", text_color=MUTED,
            hover_color=CREAM, command=lambda it=items: self._select_all(it, False),
        ).grid(row=0, column=1)

        next_row = start_row + 1
        for item in items:
            self._make_row(next_row, item)
            next_row += 1
        return next_row

    def _make_row(self, row: int, item: OrphanItem) -> None:
        frame = ctk.CTkFrame(self.results, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
        frame.grid_columnconfigure(1, weight=1)

        checkbox = ctk.CTkCheckBox(
            frame, text="", width=24, checkbox_width=20, checkbox_height=20,
            fg_color=GREEN, hover_color=DARK_GREEN, border_color=MUTED,
        )
        checkbox.grid(row=0, column=0, rowspan=2, padx=(8, 6))
        checkbox.configure(command=lambda it=item, cb=checkbox: self._on_toggle(it, cb))
        if item.selected:
            checkbox.select()
        self._checkboxes[id(item)] = checkbox

        ctk.CTkLabel(
            frame, text=item.display_name,
            font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT, anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(2, 8))

        ctk.CTkLabel(
            frame, text=item.category.value, font=ctk.CTkFont(size=10),
            text_color=DARK_GREEN, fg_color=SAND, corner_radius=6, padx=8, pady=1,
        ).grid(row=0, column=2, padx=6)

        ctk.CTkLabel(
            frame, text=human_readable_size(item.size_bytes),
            font=ctk.CTkFont(size=13, weight="bold"), text_color=GREEN,
            width=90, anchor="e",
        ).grid(row=0, column=3, sticky="e", padx=(6, 12))

        ctk.CTkLabel(
            frame, text=_short_path(item.path), font=ctk.CTkFont(size=11),
            text_color=MUTED, anchor="w",
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=(2, 12), pady=(0, 2))

    # -- Seçim ve özet -----------------------------------------------------

    def _on_toggle(self, item: OrphanItem, checkbox: ctk.CTkCheckBox) -> None:
        item.selected = bool(checkbox.get())
        self._update_summary()

    def _select_all(self, items: list[OrphanItem], value: bool) -> None:
        for item in items:
            item.selected = value
            checkbox = self._checkboxes.get(id(item))
            if checkbox is not None:
                checkbox.select() if value else checkbox.deselect()
        self._update_summary()

    def _selected_items(self) -> list[OrphanItem]:
        return [o for o in self.orphans if o.selected]

    def _update_summary(self) -> None:
        selected = self._selected_items()
        if selected:
            total = human_readable_size(sum(o.size_bytes for o in selected))
            self.summary_label.configure(text=f"{len(selected)} öğe seçili  ·  {total}")
            self.trash_button.configure(state="normal")
        else:
            self.summary_label.configure(text="Silmek istediğiniz öğeleri seçin.")
            self.trash_button.configure(state="disabled")

    # -- Çöp'e taşıma akışı ------------------------------------------------

    def _confirm_and_trash(self) -> None:
        selected = self._selected_items()
        if not selected:
            return
        total = human_readable_size(sum(o.size_bytes for o in selected))
        self._open_confirm_dialog(len(selected), total, selected)

    def _open_confirm_dialog(
        self, count: int, total: str, selected: list[OrphanItem]
    ) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Onay")
        dialog.geometry("460x220")
        dialog.configure(fg_color=CREAM)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="Çöp Kutusu'na Taşı",
            font=ctk.CTkFont(size=18, weight="bold"), text_color=DARK_GREEN,
        ).pack(padx=24, pady=(24, 8))
        ctk.CTkLabel(
            dialog,
            text=f"{count} öğe (toplam {total}) Çöp Kutusu'na taşınacak.\n"
                 "Bu işlem geri alınabilir — dosyaları Çöp'ten kurtarabilirsiniz.",
            font=ctk.CTkFont(size=13), text_color=TEXT, justify="center",
        ).pack(padx=24, pady=(0, 20))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(padx=24, pady=(0, 20))
        ctk.CTkButton(
            buttons, text="İptal", command=dialog.destroy, width=120, height=40,
            font=ctk.CTkFont(size=13), fg_color=SAND, hover_color=CARD,
            text_color=DARK_GREEN,
        ).grid(row=0, column=0, padx=8)
        ctk.CTkButton(
            buttons, text="Çöp'e Taşı",
            command=lambda: self._start_trash(dialog, selected), width=140, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=TERRA, hover_color=TERRA_DARK, text_color="#FFFFFF",
        ).grid(row=0, column=1, padx=8)

    def _start_trash(self, dialog: ctk.CTkToplevel, selected: list[OrphanItem]) -> None:
        dialog.destroy()
        self.scan_button.configure(state="disabled")
        self.trash_button.configure(state="disabled", text="Taşınıyor…")
        self._queue = queue.Queue()
        paths = [o.path for o in selected]
        threading.Thread(
            target=self._trash_worker, args=(paths, selected), daemon=True,
        ).start()
        self.after(100, self._poll_trash)

    def _trash_worker(
        self, paths: list[Path], selected: list[OrphanItem]
    ) -> None:
        succeeded, failed = trash.move_to_trash(paths)
        self._queue.put(("trash_done", (succeeded, failed, selected)))

    def _poll_trash(self) -> None:
        try:
            kind, payload = self._queue.get_nowait()
            if kind == "trash_done":
                self._on_trash_done(*payload)
                return
        except queue.Empty:
            pass
        self.after(100, self._poll_trash)

    def _on_trash_done(
        self,
        succeeded: list[Path],
        failed: list[tuple[Path, str]],
        selected: list[OrphanItem],
    ) -> None:
        self.trash_button.configure(text="Seçilenleri Çöp'e Taşı")
        self.scan_button.configure(state="normal")

        moved_paths = set(succeeded)
        freed = human_readable_size(
            sum(o.size_bytes for o in selected if o.path in moved_paths)
        )
        # Başarıyla taşınanları listeden çıkar.
        self.orphans = [o for o in self.orphans if o.path not in moved_paths]

        message = f"✓ {len(succeeded)} öğe Çöp Kutusu'na taşındı · {freed} boşaltıldı."
        if failed:
            message += f"\n⚠ {len(failed)} öğe taşınamadı (izin veya erişim hatası)."
        self._banner = message
        self._render_results()
