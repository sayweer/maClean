"""maClean masaüstü arayüzü.

Dosya sistemi kararları applications/scanner/removal/cleanup servislerinde
verilir. Arka plan işçileri widget'lara dokunmaz; sonuçlar queue üzerinden ana
Tk thread'ine aktarılır.
"""

from __future__ import annotations

import queue
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import cleanup, removal, scanner
from .applications import (
    ApplicationError,
    discover_applications,
    read_application,
    validate_removable_application,
)
from .models import (
    ApplicationRecord,
    EvidenceLevel,
    OrphanItem,
    RemovalMode,
    RemovalPlan,
    RemovalResult,
    ScanReport,
    build_trash_banner,
    human_readable_size,
)
from .state import StateStore

CREAM = "#FBF5DD"
SAND = "#E7E1B1"
GREEN = "#306D29"
DARK_GREEN = "#0D530E"
CARD = "#FFFDF5"
TEXT = "#243325"
MUTED = "#6E7A63"
TERRA = "#B5502E"
TERRA_DARK = "#93401F"
HOME = str(Path.home())


def _short_path(path: Path, max_len: int = 72) -> str:
    text = str(path)
    if text.startswith(HOME):
        text = "~" + text[len(HOME):]
    if len(text) <= max_len:
        return text
    head = max_len // 2 - 2
    tail = max_len - head - 1
    return f"{text[:head]}…{text[-tail:]}"


def _evidence_label(level: EvidenceLevel) -> str:
    return {
        EvidenceLevel.EXPLICIT_REMOVAL: "maClean ile kaldırıldı",
        EvidenceLevel.OBSERVED_MISSING: "Daha önce görülmüştü",
        EvidenceLevel.EXACT_IDENTIFIER: "Kimlik biçimi eşleşiyor",
        EvidenceLevel.NAME_ONLY: "Yalnız ad eşleşmesi",
        EvidenceLevel.SHARED_OR_UNKNOWN: "Paylaşılan / doğrulanamadı",
    }[level]


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("maClean")
        self.geometry("1120x760")
        self.minsize(900, 620)
        self.configure(fg_color=CREAM)

        self.state_store = StateStore()
        self.apps: list[ApplicationRecord] = []
        self.app_issues = []
        self.selected_app: ApplicationRecord | None = None
        self.removal_plan: RemovalPlan | None = None
        self.removal_checks: dict[Path, ctk.CTkCheckBox] = {}
        self.orphan_report = ScanReport(())
        self.orphan_checks: dict[Path, ctk.CTkCheckBox] = {}
        self._queue: queue.Queue = queue.Queue()
        self._polling = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_tabs()
        self._start_app_discovery()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="maClean",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color=DARK_GREEN,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Uygulamaları kalıntı bırakmadan kaldırın veya eski adayları güvenle inceleyin.",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _build_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=CARD,
            segmented_button_selected_color=GREEN,
            segmented_button_selected_hover_color=DARK_GREEN,
            segmented_button_unselected_color=SAND,
            segmented_button_unselected_hover_color=CREAM,
            text_color=TEXT,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=28, pady=(8, 24))
        uninstall_tab = self.tabs.add("Uygulama Kaldır")
        residue_tab = self.tabs.add("Eski Kalıntıları Tara")
        self._build_uninstall_tab(uninstall_tab)
        self._build_residue_tab(residue_tab)

    # ------------------------------------------------------------------
    # Uygulama kaldırma
    # ------------------------------------------------------------------

    def _build_uninstall_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=2)
        tab.grid_columnconfigure(1, weight=3)
        tab.grid_rowconfigure(1, weight=1)

        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        controls.grid_columnconfigure(0, weight=1)
        self.app_search = ctk.CTkEntry(
            controls,
            placeholder_text="Uygulamalarda ara…",
            height=38,
            border_color=SAND,
        )
        self.app_search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.app_search.bind("<KeyRelease>", lambda _event: self._render_app_list())
        self.choose_app_button = ctk.CTkButton(
            controls,
            text=".app Seç",
            command=self._choose_external_app,
            fg_color=SAND,
            hover_color=CREAM,
            text_color=DARK_GREEN,
            width=110,
            height=38,
        )
        self.choose_app_button.grid(row=0, column=1, padx=4)
        self.refresh_apps_button = ctk.CTkButton(
            controls,
            text="Yenile",
            command=self._start_app_discovery,
            fg_color=GREEN,
            hover_color=DARK_GREEN,
            width=90,
            height=38,
        )
        self.refresh_apps_button.grid(row=0, column=2, padx=(4, 0))

        self.app_list = ctk.CTkScrollableFrame(
            tab, fg_color=CREAM, corner_radius=10, label_text="Kurulu Uygulamalar"
        )
        self.app_list.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=(0, 12))
        self.app_list.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(tab, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=(0, 12))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        self.selected_app_label = ctk.CTkLabel(
            right,
            text="Kaldırmak için soldan bir uygulama seçin.",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=DARK_GREEN,
            anchor="w",
            justify="left",
        )
        self.selected_app_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        mode_row = ctk.CTkFrame(right, fg_color="transparent")
        mode_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        mode_row.grid_columnconfigure(0, weight=1)
        self.removal_mode = ctk.CTkSegmentedButton(
            mode_row,
            values=["Standart kaldır", "Tamamen kaldır"],
            command=lambda _value: self._start_plan_build(),
            selected_color=GREEN,
            selected_hover_color=DARK_GREEN,
            unselected_color=SAND,
            unselected_hover_color=CREAM,
            text_color=TEXT,
        )
        self.removal_mode.grid(row=0, column=0, sticky="w")
        self.removal_mode.set("Standart kaldır")

        self.plan_results = ctk.CTkScrollableFrame(
            right, fg_color=CREAM, corner_radius=10
        )
        self.plan_results.grid(row=2, column=0, sticky="nsew")
        self.plan_results.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(right, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.plan_summary = ctk.CTkLabel(
            footer, text="", text_color=MUTED, anchor="w"
        )
        self.plan_summary.grid(row=0, column=0, sticky="w")
        self.remove_button = ctk.CTkButton(
            footer,
            text="Kaldırmayı Onayla",
            command=self._confirm_removal,
            state="disabled",
            fg_color=TERRA,
            hover_color=TERRA_DARK,
            width=170,
            height=40,
        )
        self.remove_button.grid(row=0, column=1, sticky="e")

    def _start_app_discovery(self) -> None:
        self.refresh_apps_button.configure(state="disabled", text="Taranıyor…")
        self._run_worker(self._discover_apps_worker)

    def _discover_apps_worker(self) -> None:
        try:
            apps, issues = discover_applications()
            self._queue.put(("apps_done", (apps, issues)))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("worker_error", ("Uygulamalar taranamadı", str(exc))))

    def _on_apps_done(self, payload) -> None:
        apps, issues = payload
        self.apps = apps
        self.app_issues = issues
        self.state_store.update_inventory([app for app in apps if app.selectable])
        self.refresh_apps_button.configure(state="normal", text="Yenile")
        self._render_app_list()

    def _render_app_list(self) -> None:
        for child in self.app_list.winfo_children():
            child.destroy()
        query = _normalize_query(self.app_search.get())
        selectable = [app for app in self.apps if app.selectable]
        filtered = [
            app
            for app in selectable
            if not query
            or query in _normalize_query(app.name)
            or query in app.bundle_id
        ]
        for row, app in enumerate(filtered):
            button = ctk.CTkButton(
                self.app_list,
                text=f"{app.name}\n{_short_path(app.path, 52)}",
                command=lambda selected=app: self._select_application(selected),
                anchor="w",
                justify="left",
                fg_color="transparent",
                hover_color=SAND,
                text_color=TEXT,
                height=52,
            )
            button.grid(row=row, column=0, sticky="ew", pady=1)
        if not filtered:
            ctk.CTkLabel(
                self.app_list,
                text="Eşleşen uygulama bulunamadı.",
                text_color=MUTED,
            ).grid(row=0, column=0, pady=30)

    def _choose_external_app(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Kaldırılacak .app paketini seçin",
            filetypes=[("macOS Uygulaması", "*.app")],
        )
        if not chosen:
            return
        try:
            app = read_application(Path(chosen), selectable=True)
        except ApplicationError as exc:
            self._show_message("Uygulama seçilemedi", str(exc), error=True)
            return
        self._select_application(app)

    def _select_application(self, app: ApplicationRecord) -> None:
        error = validate_removable_application(app)
        if error:
            self._show_message("Bu uygulama kaldırılamaz", error, error=True)
            return
        self.selected_app = app
        self.selected_app_label.configure(
            text=f"{app.name}\n{_short_path(app.path)}"
        )
        self._start_plan_build()

    def _start_plan_build(self) -> None:
        if self.selected_app is None:
            return
        self.remove_button.configure(state="disabled", text="Plan hazırlanıyor…")
        self._clear_frame(self.plan_results)
        ctk.CTkLabel(
            self.plan_results,
            text="İlişkili dosyalar doğrulanıyor…",
            text_color=MUTED,
        ).grid(row=0, column=0, pady=40)
        app = self.selected_app
        mode = (
            RemovalMode.FULL
            if self.removal_mode.get() == "Tamamen kaldır"
            else RemovalMode.STANDARD
        )
        self._run_worker(lambda: self._plan_worker(app, mode))

    def _plan_worker(self, app: ApplicationRecord, mode: RemovalMode) -> None:
        try:
            plan = removal.build_removal_plan(app, mode, self.apps)
            self._queue.put(("plan_done", plan))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("worker_error", ("Kaldırma planı oluşturulamadı", str(exc))))

    def _render_removal_plan(self, plan: RemovalPlan) -> None:
        self.removal_plan = plan
        self.removal_checks.clear()
        self._clear_frame(self.plan_results)
        row = 0
        self._plan_row(
            row,
            "Uygulama paketi",
            plan.application.path,
            None,
            "Önce Çöp Kutusu'na taşınacak; bu başarısız olursa işlem durur.",
            locked=True,
        )
        row += 1
        for item in plan.items:
            checkbox = self._plan_row(
                row,
                f"{item.display_name} · {item.category.value if item.category else ''}",
                item.path,
                item.size_bytes,
                f"{_evidence_label(item.evidence)} · {item.reason}",
                selected=item.selected_by_default,
                disabled=not item.selectable,
            )
            if checkbox is not None:
                self.removal_checks[item.path] = checkbox
            row += 1
        if plan.issues:
            ctk.CTkLabel(
                self.plan_results,
                text=f"⚠ {len(plan.issues)} konum tam olarak okunamadı; bu öğeler seçilmedi.",
                text_color=TERRA,
                wraplength=560,
                justify="left",
            ).grid(row=row, column=0, sticky="w", padx=10, pady=10)
        self.remove_button.configure(state="normal", text="Kaldırmayı Onayla")
        self._update_plan_summary()

    def _plan_row(
        self,
        row: int,
        title: str,
        path: Path,
        size: int | None,
        reason: str,
        *,
        selected: bool = False,
        disabled: bool = False,
        locked: bool = False,
    ) -> ctk.CTkCheckBox | None:
        frame = ctk.CTkFrame(self.plan_results, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=4, pady=2)
        frame.grid_columnconfigure(1, weight=1)
        checkbox: ctk.CTkCheckBox | None
        if locked:
            ctk.CTkLabel(
                frame, text="✓", text_color=GREEN, width=24
            ).grid(row=0, column=0, rowspan=3, padx=(4, 6))
            checkbox = None
        else:
            checkbox = ctk.CTkCheckBox(
                frame,
                text="",
                width=24,
                state="disabled" if disabled else "normal",
                command=self._update_plan_summary,
                fg_color=GREEN,
                hover_color=DARK_GREEN,
            )
            checkbox.grid(row=0, column=0, rowspan=3, padx=(4, 6))
            if selected:
                checkbox.select()
        ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            frame,
            text=f"{human_readable_size(size)} · {_short_path(path, 60)}",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            anchor="w",
        ).grid(row=1, column=1, sticky="w")
        ctk.CTkLabel(
            frame,
            text=reason,
            text_color=TERRA if disabled else MUTED,
            font=ctk.CTkFont(size=10),
            wraplength=470,
            justify="left",
            anchor="w",
        ).grid(row=2, column=1, sticky="w", pady=(0, 3))
        ctk.CTkButton(
            frame,
            text="Finder",
            width=58,
            height=24,
            fg_color=SAND,
            hover_color=CREAM,
            text_color=DARK_GREEN,
            command=lambda target=path: self._reveal_in_finder(target),
        ).grid(row=0, column=2, rowspan=2, padx=4)
        return checkbox

    def _selected_plan_paths(self) -> set[Path]:
        return {
            path for path, checkbox in self.removal_checks.items() if checkbox.get()
        }

    def _update_plan_summary(self) -> None:
        if self.removal_plan is None:
            return
        selected = self._selected_plan_paths()
        items = [item for item in self.removal_plan.items if item.path in selected]
        known_total = sum(item.size_bytes or 0 for item in items)
        self.plan_summary.configure(
            text=f"Uygulama + {len(items)} ilişkili öğe · {human_readable_size(known_total)}"
        )

    def _confirm_removal(self) -> None:
        if self.removal_plan is None:
            return
        selected = self._selected_plan_paths()
        mode = (
            "Tamamen kaldır"
            if self.removal_plan.mode is RemovalMode.FULL
            else "Standart kaldır"
        )
        message = (
            f"{self.removal_plan.application.name} ve {len(selected)} ilişkili öğe "
            f"Çöp Kutusu'na taşınacak.\n\nMod: {mode}\n"
            "Uygulama taşınamazsa ilişkili verilere dokunulmaz."
        )
        self._confirm_dialog(
            "Kaldırmayı Onayla",
            message,
            lambda: self._start_removal(selected),
        )

    def _start_removal(self, selected: set[Path]) -> None:
        if self.removal_plan is None:
            return
        plan = self.removal_plan
        self.remove_button.configure(state="disabled", text="Taşınıyor…")
        self._run_worker(lambda: self._removal_worker(plan, selected))

    def _removal_worker(self, plan: RemovalPlan, selected: set[Path]) -> None:
        try:
            result = removal.execute_removal(
                plan, selected, state_store=self.state_store
            )
            self._queue.put(("removal_done", result))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("worker_error", ("Kaldırma tamamlanamadı", str(exc))))

    def _on_removal_done(self, result: RemovalResult) -> None:
        self.remove_button.configure(state="normal", text="Kaldırmayı Onayla")
        if not result.application_moved:
            self._show_message(
                "Kaldırma durduruldu",
                result.aborted_reason or "Uygulama taşınamadı.",
                error=True,
            )
            return
        message = f"✓ Uygulama ve {max(0, len(result.moved_paths) - 1)} ilişkili öğe Çöp'e taşındı."
        if result.failed_paths:
            message += f"\n⚠ {len(result.failed_paths)} öğe taşınamadı; eski kalıntı taramasından tekrar deneyebilirsiniz."
        self._show_message("Kaldırma tamamlandı", message)
        self.selected_app = None
        self.removal_plan = None
        self.selected_app_label.configure(text="Kaldırmak için soldan bir uygulama seçin.")
        self._clear_frame(self.plan_results)
        self.plan_summary.configure(text="")
        self.remove_button.configure(state="disabled")
        self._start_app_discovery()

    # ------------------------------------------------------------------
    # Eski kalıntı tarama
    # ------------------------------------------------------------------

    def _build_residue_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        controls.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            controls,
            text="Heuristik sonuçlar otomatik seçilmez. Son 30 günde değişen veya okunamayan öğeler korunur.",
            text_color=MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.scan_button = ctk.CTkButton(
            controls,
            text="Taramayı Başlat",
            command=self._start_orphan_scan,
            fg_color=GREEN,
            hover_color=DARK_GREEN,
            width=150,
            height=38,
        )
        self.scan_button.grid(row=0, column=1, sticky="e")

        self.scan_status = ctk.CTkLabel(
            tab, text="", text_color=MUTED, anchor="w"
        )
        self.scan_status.grid(row=1, column=0, sticky="ew", padx=14)

        self.orphan_results = ctk.CTkScrollableFrame(
            tab, fg_color=CREAM, corner_radius=10
        )
        self.orphan_results.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        self.orphan_results.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.orphan_results,
            text="Başlamak için “Taramayı Başlat”a tıklayın.",
            text_color=MUTED,
        ).grid(row=0, column=0, pady=50)

        footer = ctk.CTkFrame(tab, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        footer.grid_columnconfigure(0, weight=1)
        self.orphan_summary = ctk.CTkLabel(
            footer, text="", text_color=MUTED, anchor="w"
        )
        self.orphan_summary.grid(row=0, column=0, sticky="w")
        self.cleanup_button = ctk.CTkButton(
            footer,
            text="Seçilenleri Çöp'e Taşı",
            command=self._confirm_cleanup,
            state="disabled",
            fg_color=TERRA,
            hover_color=TERRA_DARK,
            width=190,
            height=40,
        )
        self.cleanup_button.grid(row=0, column=1, sticky="e")

    def _start_orphan_scan(self) -> None:
        self.scan_button.configure(state="disabled", text="Taranıyor…")
        self.cleanup_button.configure(state="disabled")
        self.scan_status.configure(text="Kurulu uygulamalar doğrulanıyor…")
        self._clear_frame(self.orphan_results)
        self._run_worker(self._orphan_scan_worker)

    def _orphan_scan_worker(self) -> None:
        try:
            apps, app_issues = discover_applications()
            ids = {
                identifier
                for app in apps
                for identifier in app.all_bundle_ids
            }
            names = {app.name for app in apps}
            report = scanner.scan_orphans(
                ids,
                names,
                progress_callback=lambda location: self._queue.put(
                    ("scan_progress", location)
                ),
                state_store=self.state_store,
            )
            combined = ScanReport(report.items, (*app_issues, *report.issues))
            self._queue.put(("scan_done", (combined, apps)))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("worker_error", ("Tarama tamamlanamadı", str(exc))))

    def _on_scan_done(self, payload) -> None:
        report, apps = payload
        self.orphan_report = report
        self.apps = apps
        self.state_store.update_inventory([app for app in apps if app.selectable])
        self.scan_button.configure(state="normal", text="Yeniden Tara")
        self.scan_status.configure(
            text=(
                f"{len(report.items)} inceleme adayı bulundu."
                + (
                    f" ⚠ {len(report.issues)} konum eksik veya okunamadı."
                    if report.issues
                    else ""
                )
            )
        )
        self._render_orphans()

    def _render_orphans(self) -> None:
        self._clear_frame(self.orphan_results)
        self.orphan_checks.clear()
        if not self.orphan_report.items:
            ctk.CTkLabel(
                self.orphan_results,
                text="İncelenecek eski kalıntı adayı bulunamadı.",
                text_color=GREEN,
                font=ctk.CTkFont(size=15, weight="bold"),
            ).grid(row=0, column=0, pady=50)
            return
        for row, item in enumerate(self.orphan_report.items):
            frame = ctk.CTkFrame(self.orphan_results, fg_color="transparent")
            frame.grid(row=row, column=0, sticky="ew", padx=4, pady=2)
            frame.grid_columnconfigure(1, weight=1)
            checkbox = ctk.CTkCheckBox(
                frame,
                text="",
                width=24,
                state="normal" if item.selectable else "disabled",
                command=self._update_orphan_summary,
                fg_color=GREEN,
                hover_color=DARK_GREEN,
            )
            checkbox.grid(row=0, column=0, rowspan=3, padx=(4, 6))
            if item.selectable:
                self.orphan_checks[item.path] = checkbox
            ctk.CTkLabel(
                frame,
                text=f"{item.display_name} · {item.category.value}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
                anchor="w",
            ).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(
                frame,
                text=f"{human_readable_size(item.size_bytes)} · {_short_path(item.path, 72)}",
                text_color=MUTED,
                font=ctk.CTkFont(size=10),
                anchor="w",
            ).grid(row=1, column=1, sticky="w")
            ctk.CTkLabel(
                frame,
                text=f"{_evidence_label(item.evidence)} · {item.reason}",
                text_color=TERRA if not item.selectable else MUTED,
                font=ctk.CTkFont(size=10),
                wraplength=780,
                justify="left",
                anchor="w",
            ).grid(row=2, column=1, sticky="w", pady=(0, 3))
            ctk.CTkButton(
                frame,
                text="Finder",
                width=58,
                height=24,
                fg_color=SAND,
                hover_color=CREAM,
                text_color=DARK_GREEN,
                command=lambda target=item.path: self._reveal_in_finder(target),
            ).grid(row=0, column=2, rowspan=2, padx=4)
        self._update_orphan_summary()

    def _selected_orphan_paths(self) -> set[Path]:
        return {
            path for path, checkbox in self.orphan_checks.items() if checkbox.get()
        }

    def _update_orphan_summary(self) -> None:
        selected = self._selected_orphan_paths()
        items = [item for item in self.orphan_report.items if item.path in selected]
        total = sum(item.size_bytes or 0 for item in items)
        self.orphan_summary.configure(
            text=f"{len(items)} öğe seçili · {human_readable_size(total)}"
        )
        self.cleanup_button.configure(state="normal" if items else "disabled")

    def _confirm_cleanup(self) -> None:
        selected = self._selected_orphan_paths()
        if not selected:
            return
        self._confirm_dialog(
            "Çöp Kutusu'na Taşı",
            f"{len(selected)} eski kalıntı adayı Çöp Kutusu'na taşınacak.\n"
            "İşlemden önce yollar ve dosya kimlikleri tekrar doğrulanacak.",
            lambda: self._start_cleanup(selected),
        )

    def _start_cleanup(self, selected: set[Path]) -> None:
        self.cleanup_button.configure(state="disabled", text="Taşınıyor…")
        items = self.orphan_report.items
        self._run_worker(lambda: self._cleanup_worker(items, selected))

    def _cleanup_worker(self, items, selected: set[Path]) -> None:
        try:
            result = cleanup.cleanup_orphans(items, selected)
            self._queue.put(("cleanup_done", result))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("worker_error", ("Temizlik tamamlanamadı", str(exc))))

    def _on_cleanup_done(self, result) -> None:
        self.cleanup_button.configure(text="Seçilenleri Çöp'e Taşı")
        moved = set(result.moved_paths)
        selected_items = [
            item for item in self.orphan_report.items if item.path in moved
        ]
        freed = human_readable_size(
            sum(item.size_bytes or 0 for item in selected_items)
        )
        failed_items = [
            item
            for item in self.orphan_report.items
            if any(path == item.path for path, _ in result.failed_paths)
        ]
        banner = build_trash_banner(
            len(result.moved_paths),
            freed,
            failed_items,
            [message for _, message in result.failed_paths],
        )
        self.orphan_report = ScanReport(
            tuple(item for item in self.orphan_report.items if item.path not in moved),
            self.orphan_report.issues,
        )
        self._render_orphans()
        self._show_message("Temizlik sonucu", banner, error=bool(result.failed_paths))

    # ------------------------------------------------------------------
    # Ortak yardımcılar
    # ------------------------------------------------------------------

    def _run_worker(self, target) -> None:
        threading.Thread(target=target, daemon=True).start()
        if not self._polling:
            self._polling = True
            self.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        handled = False
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                handled = True
                if kind == "apps_done":
                    self._on_apps_done(payload)
                elif kind == "plan_done":
                    self._render_removal_plan(payload)
                elif kind == "removal_done":
                    self._on_removal_done(payload)
                elif kind == "scan_progress":
                    self.scan_status.configure(text=f"Taranıyor: {payload}")
                elif kind == "scan_done":
                    self._on_scan_done(payload)
                elif kind == "cleanup_done":
                    self._on_cleanup_done(payload)
                elif kind == "worker_error":
                    title, message = payload
                    self._recover_buttons()
                    self._show_message(title, message, error=True)
        except queue.Empty:
            pass
        if self._has_active_worker() or not self._queue.empty():
            self.after(100, self._poll_queue)
        else:
            self._polling = False

    @staticmethod
    def _has_active_worker() -> bool:
        return any(
            thread is not threading.current_thread()
            and thread.daemon
            and thread.is_alive()
            for thread in threading.enumerate()
        )

    def _recover_buttons(self) -> None:
        self.refresh_apps_button.configure(state="normal", text="Yenile")
        self.remove_button.configure(
            state="normal" if self.removal_plan else "disabled",
            text="Kaldırmayı Onayla",
        )
        self.scan_button.configure(state="normal", text="Yeniden Tara")
        self.cleanup_button.configure(
            state="normal" if self._selected_orphan_paths() else "disabled",
            text="Seçilenleri Çöp'e Taşı",
        )

    def _confirm_dialog(self, title: str, message: str, action) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("500x260")
        dialog.configure(fg_color=CREAM)
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(
            dialog,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=DARK_GREEN,
        ).pack(padx=24, pady=(24, 8))
        ctk.CTkLabel(
            dialog,
            text=message,
            font=ctk.CTkFont(size=13),
            text_color=TEXT,
            justify="center",
            wraplength=440,
        ).pack(padx=24, pady=(0, 20))
        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(pady=(0, 20))
        ctk.CTkButton(
            buttons,
            text="İptal",
            command=dialog.destroy,
            fg_color=SAND,
            hover_color=CARD,
            text_color=DARK_GREEN,
            width=120,
        ).grid(row=0, column=0, padx=8)

        def confirm() -> None:
            dialog.destroy()
            action()

        confirm_button = ctk.CTkButton(
            buttons,
            text="Devam Et",
            command=confirm,
            fg_color=TERRA,
            hover_color=TERRA_DARK,
            width=140,
        )
        confirm_button.grid(row=0, column=1, padx=8)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Return>", lambda _event: confirm())
        confirm_button.focus_set()

    def _show_message(
        self,
        title: str,
        message: str,
        *,
        error: bool = False,
    ) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("520x270")
        dialog.configure(fg_color=CREAM)
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(
            dialog,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TERRA if error else DARK_GREEN,
        ).pack(padx=24, pady=(24, 8))
        ctk.CTkLabel(
            dialog,
            text=message,
            font=ctk.CTkFont(size=13),
            text_color=TEXT,
            justify="left",
            wraplength=460,
        ).pack(padx=24, pady=(0, 20))
        button = ctk.CTkButton(
            dialog,
            text="Tamam",
            command=dialog.destroy,
            fg_color=GREEN,
            hover_color=DARK_GREEN,
            width=120,
        )
        button.pack(pady=(0, 20))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Return>", lambda _event: dialog.destroy())
        button.focus_set()

    @staticmethod
    def _clear_frame(frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _reveal_in_finder(self, path: Path) -> None:
        try:
            subprocess.Popen(["open", "-R", str(path)])
        except OSError as exc:
            self._show_message("Finder açılamadı", str(exc), error=True)


def _normalize_query(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())
