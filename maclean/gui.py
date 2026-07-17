"""maClean desktop interface.

CustomTkinter provides the shell while large result sets use a native ttk
Treeview. This keeps widget counts nearly constant even with hundreds of rows.
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import tkinter as tk
import unicodedata
from datetime import datetime
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
    RemovalItem,
    RemovalMode,
    RemovalPlan,
    RemovalResult,
    ScanReport,
    build_trash_banner,
    human_readable_size,
)
from .state import StateStore
from .ui_components import FastTable, TableColumn, TableRow

logger = logging.getLogger(__name__)

Color = tuple[str, str]

BG: Color = ("#F4F3ED", "#101411")
SURFACE: Color = ("#FFFDF8", "#182019")
SURFACE_SUBTLE: Color = ("#E9E9DF", "#222B23")
BORDER: Color = ("#D5D8CD", "#344238")
PRIMARY: Color = ("#2F6B3B", "#78B985")
PRIMARY_HOVER: Color = ("#24572F", "#91C99B")
PRIMARY_SOFT: Color = ("#DDEBDD", "#263B2A")
TEXT: Color = ("#202A22", "#EDF3EE")
MUTED: Color = ("#59665C", "#AAB8AD")
DESTRUCTIVE: Color = ("#A5452B", "#E38B6D")
DESTRUCTIVE_HOVER: Color = ("#843520", "#F0A084")
WARNING: Color = ("#8A6416", "#E5BD63")
WARNING_SOFT: Color = ("#F6EDCE", "#392F18")
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


def _normalize_query(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        character
        for character in normalized
        if character.isalnum() and not unicodedata.combining(character)
    )


def _evidence_label(level: EvidenceLevel) -> str:
    return {
        EvidenceLevel.EXPLICIT_REMOVAL: "maClean kaldırdı",
        EvidenceLevel.OBSERVED_MISSING: "Önceden görüldü",
        EvidenceLevel.EXACT_IDENTIFIER: "Kimlik adayı",
        EvidenceLevel.NAME_ONLY: "Ad eşleşmesi",
        EvidenceLevel.SHARED_OR_UNKNOWN: "Paylaşılan / belirsiz",
    }[level]


def _date_label(value: datetime) -> str:
    if value.year <= 1970:
        return "Tarih bilinmiyor"
    return value.strftime("%d.%m.%Y · %H:%M")


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("maClean")
        self.geometry("1200x800")
        self.minsize(980, 680)
        self.configure(fg_color=BG)

        self.state_store = StateStore()
        self.apps: list[ApplicationRecord] = []
        self.app_issues = []
        self.selected_app: ApplicationRecord | None = None
        self.removal_plan: RemovalPlan | None = None
        self.plan_selected: set[Path] = set()
        self.orphan_report = ScanReport(())
        self.orphan_selected: set[Path] = set()
        self._queue: queue.Queue = queue.Queue()
        self._polling = False
        self._worker_count = 0
        # Yeni bir tarama isteği bu sayacı artırır; arka planda süren eski
        # worker kendi neslinin geçersizleştiğini görüp erken çıkar.
        self._scan_generation = 0
        self._search_after: str | None = None
        self._appearance = ctk.get_appearance_mode()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_tabs()
        self._build_menu()
        self.after(1000, self._sync_native_theme)
        self._start_app_discovery()
        self._check_full_disk_access()

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=32, pady=(22, 8))
        header.grid_columnconfigure(0, weight=1)

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_row,
            text="maClean",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_row,
            text="  Yerel · Kalıcı silme yok",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PRIMARY,
            fg_color=PRIMARY_SOFT,
            corner_radius=10,
            padx=10,
            pady=4,
        ).grid(row=0, column=1, padx=(12, 0), sticky="w")
        ctk.CTkLabel(
            header,
            text=(
                "Uygulamaları kalıntı bırakmadan kaldırın; eski adayları "
                "kanıt seviyeleriyle inceleyin."
            ),
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
            segmented_button_selected_color=PRIMARY,
            segmented_button_selected_hover_color=PRIMARY_HOVER,
            segmented_button_unselected_color=SURFACE_SUBTLE,
            segmented_button_unselected_hover_color=PRIMARY_SOFT,
            text_color=TEXT,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=32, pady=(8, 28))
        uninstall_tab = self.tabs.add("Uygulama Kaldır")
        residue_tab = self.tabs.add("Eski Kalıntıları Tara")
        self._build_uninstall_tab(uninstall_tab)
        self._build_residue_tab(residue_tab)

    def _table(
        self,
        master,
        *,
        columns: tuple[TableColumn, ...],
        checkable: bool,
        on_focus=None,
        on_activate=None,
        on_check_change=None,
    ):
        return FastTable(
            master,
            columns=columns,
            checkable=checkable,
            on_focus=on_focus,
            on_activate=on_activate,
            on_check_change=on_check_change,
            bg_color=BG,
            surface_color=SURFACE,
            border_color=BORDER,
            text_color=TEXT,
            muted_color=MUTED,
            accent_color=PRIMARY,
            warning_color=WARNING,
        )

    # ------------------------------------------------------------------
    # Uninstaller
    # ------------------------------------------------------------------

    def _build_uninstall_tab(self, tab: ctk.CTkFrame) -> None:
        tab.configure(fg_color=SURFACE)
        tab.grid_columnconfigure(0, weight=2, minsize=330)
        tab.grid_columnconfigure(1, weight=3, minsize=500)
        tab.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=14,
            pady=(14, 10),
        )
        toolbar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            toolbar,
            text="Kurulu uygulamalar",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, padx=(0, 16), sticky="w")
        self.app_search = ctk.CTkEntry(
            toolbar,
            placeholder_text="Uygulama veya bundle kimliği ara",
            height=40,
            border_color=BORDER,
            fg_color=BG,
            text_color=TEXT,
            placeholder_text_color=MUTED,
        )
        self.app_search.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.app_search.bind("<KeyRelease>", self._schedule_app_filter)
        self.choose_app_button = self._secondary_button(
            toolbar,
            ".app Seç",
            self._choose_external_app,
            width=104,
        )
        self.choose_app_button.grid(row=0, column=2, padx=4)
        self.refresh_apps_button = self._primary_button(
            toolbar,
            "Yenile",
            self._start_app_discovery,
            width=92,
        )
        self.refresh_apps_button.grid(row=0, column=3, padx=(4, 0))

        left = ctk.CTkFrame(tab, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew", padx=(14, 7), pady=(0, 14))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)
        self.app_table: FastTable[ApplicationRecord] = self._table(
            left,
            columns=(
                TableColumn("name", "Uygulama", 190, stretch=True),
                TableColumn("bundle", "Bundle kimliği", 220, stretch=True),
            ),
            checkable=False,
            on_focus=self._select_application,
            on_activate=self._select_application,
        )
        self.app_table.grid(row=0, column=0, sticky="nsew")
        self.app_table.show_state(
            "Uygulamalar hazırlanıyor",
            "Kurulu paketler güvenli konumlardan okunuyor.",
        )
        self.app_count_label = ctk.CTkLabel(
            left,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        )
        self.app_count_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        right = ctk.CTkFrame(tab, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(7, 14), pady=(0, 14))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        self.app_summary_card = ctk.CTkFrame(
            right,
            fg_color=BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=10,
        )
        self.app_summary_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.app_summary_card.grid_columnconfigure(0, weight=1)
        self.selected_app_name = ctk.CTkLabel(
            self.app_summary_card,
            text="Bir uygulama seçin",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        self.selected_app_name.grid(
            row=0, column=0, sticky="ew", padx=16, pady=(14, 2)
        )
        self.selected_app_meta = ctk.CTkLabel(
            self.app_summary_card,
            text="İlişkili dosyalar seçiminizden sonra doğrulanır.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
            justify="left",
        )
        self.selected_app_meta.grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 14)
        )

        mode_row = ctk.CTkFrame(right, fg_color="transparent")
        mode_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        mode_row.grid_columnconfigure(1, weight=1)
        self.removal_mode = ctk.CTkSegmentedButton(
            mode_row,
            values=["Standart", "Tamamen"],
            command=self._on_mode_change,
            selected_color=PRIMARY,
            selected_hover_color=PRIMARY_HOVER,
            unselected_color=SURFACE_SUBTLE,
            unselected_hover_color=PRIMARY_SOFT,
            text_color=TEXT,
            height=38,
        )
        self.removal_mode.grid(row=0, column=0, sticky="w")
        self.removal_mode.set("Standart")
        self.mode_description = ctk.CTkLabel(
            mode_row,
            text="Geçici verileri kaldırır; kişisel ayarları korur.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        )
        self.mode_description.grid(row=0, column=1, padx=(12, 0), sticky="w")

        content = ctk.CTkFrame(right, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.plan_table: FastTable[RemovalItem] = self._table(
            content,
            columns=(
                TableColumn("name", "İlişkili öğe", 220, stretch=True),
                TableColumn("category", "Kategori", 140),
                TableColumn("size", "Boyut", 90, anchor="e"),
                TableColumn("evidence", "Kanıt", 125),
            ),
            checkable=True,
            on_focus=self._show_plan_detail,
            on_activate=self._show_plan_detail,
            on_check_change=self._update_plan_summary,
        )
        self.plan_table.grid(row=0, column=0, sticky="nsew")
        self.plan_table.show_state(
            "Kaldırma planı bekliyor",
            "Soldaki listeden bir uygulama seçin.",
        )

        self.plan_detail = self._detail_panel(content)
        self.plan_detail.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.plan_detail.grid_remove()

        footer = ctk.CTkFrame(right, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.plan_summary = ctk.CTkLabel(
            footer,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        self.plan_summary.grid(row=0, column=0, sticky="w")
        self.remove_button = self._destructive_button(
            footer,
            "Kaldırmayı Onayla",
            self._confirm_removal,
            width=178,
        )
        self.remove_button.configure(state="disabled")
        self.remove_button.grid(row=0, column=1, sticky="e")

    def _schedule_app_filter(self, _event=None) -> None:
        if self._search_after:
            self.after_cancel(self._search_after)
        self._search_after = self.after(120, self._render_app_list)

    def _start_app_discovery(self) -> None:
        self.refresh_apps_button.configure(state="disabled", text="Taranıyor")
        self.app_table.show_state(
            "Uygulamalar hazırlanıyor",
            "Kurulu paketler ve yardımcı bileşenler okunuyor.",
        )
        self._run_worker(self._discover_apps_worker)

    def _discover_apps_worker(self) -> None:
        try:
            apps, issues = discover_applications()
            self._queue.put(("apps_done", (apps, issues)))
        except Exception as exc:  # noqa: BLE001
            self._report_worker_error("apps", exc)

    def _on_apps_done(self, payload) -> None:
        apps, issues = payload
        self.apps = apps
        self.app_issues = issues
        self.state_store.update_inventory([app for app in apps if app.selectable])
        self.refresh_apps_button.configure(state="normal", text="Yenile")
        self._render_app_list()

    def _render_app_list(self) -> None:
        query = _normalize_query(self.app_search.get())
        selectable = [app for app in self.apps if app.selectable]
        filtered = [
            app
            for app in selectable
            if not query
            or query in _normalize_query(app.name)
            or query in _normalize_query(app.bundle_id)
        ]
        rows = [
            TableRow(
                iid=f"app-{index}",
                cells=(app.name, app.bundle_id),
                payload=app,
                sort_values=(app.name.casefold(), app.bundle_id),
            )
            for index, app in enumerate(filtered)
        ]
        if rows:
            self.app_table.set_rows(rows, focus_first=False)
        elif query:
            self.app_table.set_rows([], focus_first=False)
            self.app_table.show_state(
                "Eşleşme bulunamadı",
                "Arama metnini kısaltın veya farklı konumdaki .app paketini seçin.",
                action_label=".app Seç",
                action=self._choose_external_app,
            )
        else:
            self.app_table.set_rows([], focus_first=False)
            self.app_table.show_state(
                "Uygulama bulunamadı",
                "Standart uygulama klasörleri okunamadı veya boş.",
                action_label="Yeniden Dene",
                action=self._start_app_discovery,
            )
        suffix = f" · {len(self.app_issues)} okuma uyarısı" if self.app_issues else ""
        self.app_count_label.configure(
            text=f"{len(filtered)} uygulama gösteriliyor{suffix}"
        )

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
            self._show_message(
                "Uygulama seçilemedi",
                str(exc),
                error=True,
                recovery="Farklı bir .app paketi seçin.",
            )
            return
        self._select_application(app)

    def _select_application(self, app: ApplicationRecord | None) -> None:
        if app is None or app == self.selected_app:
            return
        error = validate_removable_application(app)
        if error:
            self._show_message(
                "Bu uygulama kaldırılamaz",
                error,
                error=True,
                recovery="Başka bir uygulama seçin.",
            )
            return
        self.selected_app = app
        self.selected_app_name.configure(text=app.name)
        self.selected_app_meta.configure(
            text=f"{app.bundle_id}\n{_short_path(app.path, 88)}"
        )
        self._start_plan_build()

    def _on_mode_change(self, value: str) -> None:
        self.mode_description.configure(
            text=(
                "Geçici verileri kaldırır; kişisel ayarları korur."
                if value == "Standart"
                else "Doğrulanmış ayarları ve özel uygulama verilerini de kaldırır."
            )
        )
        self._start_plan_build()

    def _start_plan_build(self) -> None:
        if self.selected_app is None:
            return
        self.remove_button.configure(state="disabled", text="Hazırlanıyor")
        self.plan_detail.grid_remove()
        self.plan_table.show_state(
            "Kaldırma planı hazırlanıyor",
            "Bundle kimlikleri, yardımcı bileşenler ve paylaşılan alanlar doğrulanıyor.",
        )
        app = self.selected_app
        mode = (
            RemovalMode.FULL
            if self.removal_mode.get() == "Tamamen"
            else RemovalMode.STANDARD
        )
        self._run_worker(lambda: self._plan_worker(app, mode))

    def _plan_worker(self, app: ApplicationRecord, mode: RemovalMode) -> None:
        try:
            plan = removal.build_removal_plan(app, mode, self.apps)
            self._queue.put(("plan_done", plan))
        except Exception as exc:  # noqa: BLE001
            self._report_worker_error("plan", exc)

    def _render_removal_plan(self, plan: RemovalPlan) -> None:
        if self.selected_app and plan.application.path != self.selected_app.path:
            return
        expected_mode = (
            RemovalMode.FULL
            if self.removal_mode.get() == "Tamamen"
            else RemovalMode.STANDARD
        )
        if plan.mode is not expected_mode:
            return
        self.removal_plan = plan
        self.plan_selected = set(plan.default_selected_paths)
        rows = [
            TableRow(
                iid=f"plan-{index}",
                cells=(
                    item.display_name,
                    item.category.value if item.category else "Uygulama",
                    human_readable_size(item.size_bytes),
                    _evidence_label(item.evidence),
                ),
                payload=item,
                selectable=item.selectable,
                checked=item.path in self.plan_selected,
                tone="warning" if not item.selectable else "normal",
                sort_values=(
                    item.display_name.casefold(),
                    item.category.value if item.category else "",
                    item.size_bytes if item.size_bytes is not None else -1,
                    _evidence_label(item.evidence),
                ),
            )
            for index, item in enumerate(plan.items)
        ]
        self.plan_table.set_rows(rows)
        if not rows:
            self.plan_table.show_state(
                "İlişkili dosya bulunamadı",
                "Uygulama paketi yine de güvenle Çöp Kutusu'na taşınabilir.",
            )
            self.plan_detail.grid_remove()
        issue_note = (
            f" · {len(plan.issues)} okunamayan konum korundu"
            if plan.issues
            else ""
        )
        self.remove_button.configure(state="normal", text="Kaldırmayı Onayla")
        self._update_plan_summary(extra=issue_note)

    def _sync_plan_checked(self) -> None:
        if self.removal_plan is None:
            return
        visible = {
            row.payload.path for row in self.plan_table.model.rows.values()
        }
        checked = {item.path for item in self.plan_table.checked_payloads()}
        self.plan_selected.difference_update(visible)
        self.plan_selected.update(checked)

    def _update_plan_summary(self, *, extra: str = "") -> None:
        if self.removal_plan is None:
            return
        self._sync_plan_checked()
        items = [
            item
            for item in self.removal_plan.items
            if item.path in self.plan_selected
        ]
        total = sum(item.size_bytes or 0 for item in items)
        self.plan_summary.configure(
            text=(
                f"Uygulama + {len(items)} öğe · "
                f"{human_readable_size(total)}{extra}"
            )
        )

    def _show_plan_detail(self, item: RemovalItem | None) -> None:
        if item is None:
            self.plan_detail.grid_remove()
            return
        self._set_detail(
            self.plan_detail,
            title=item.display_name,
            meta=(
                f"{item.category.value if item.category else 'Uygulama'} · "
                f"{human_readable_size(item.size_bytes)} · "
                f"{_date_label(item.last_modified)}"
            ),
            body=item.reason,
            path=item.path,
        )
        self.plan_detail.grid()

    def _confirm_removal(self) -> None:
        if self.removal_plan is None:
            return
        self._sync_plan_checked()
        mode = "Tamamen kaldır" if self.removal_plan.mode is RemovalMode.FULL else "Standart kaldır"
        self._confirm_dialog(
            "Kaldırmayı onayla",
            (
                f"{self.removal_plan.application.name} ve "
                f"{len(self.plan_selected)} ilişkili öğe Çöp Kutusu'na taşınacak."
            ),
            detail=(
                f"Mod: {mode}\n"
                "Uygulama paketi taşınamazsa ilişkili verilere dokunulmaz."
            ),
            action=lambda: self._start_removal(set(self.plan_selected)),
            trigger=self.remove_button,
        )

    def _start_removal(self, selected: set[Path]) -> None:
        if self.removal_plan is None:
            return
        plan = self.removal_plan
        self.remove_button.configure(state="disabled", text="Taşınıyor")
        self._run_worker(lambda: self._removal_worker(plan, selected))

    def _removal_worker(self, plan: RemovalPlan, selected: set[Path]) -> None:
        try:
            result = removal.execute_removal(
                plan,
                selected,
                state_store=self.state_store,
            )
            self._queue.put(("removal_done", result))
        except Exception as exc:  # noqa: BLE001
            self._report_worker_error("removal", exc)

    def _on_removal_done(self, result: RemovalResult) -> None:
        self.remove_button.configure(state="normal", text="Kaldırmayı Onayla")
        if not result.application_moved:
            self._show_message(
                "Kaldırma durduruldu",
                result.aborted_reason or "Uygulama taşınamadı.",
                error=True,
                recovery="Uygulamayı kapatın veya izinleri kontrol edip yeniden deneyin.",
            )
            return
        moved_count = max(0, len(result.moved_paths) - 1)
        detail = f"Uygulama ve {moved_count} ilişkili öğe Çöp Kutusu'na taşındı."
        if result.failed_paths:
            detail += (
                f"\n{len(result.failed_paths)} öğe korunarak yerinde bırakıldı; "
                "eski kalıntı taramasından tekrar inceleyebilirsiniz."
            )
        self._show_message(
            "Kaldırma tamamlandı",
            detail,
            recovery="İsterseniz Çöp Kutusu'ndan geri yükleyebilirsiniz.",
        )
        self.selected_app = None
        self.removal_plan = None
        self.plan_selected.clear()
        self.selected_app_name.configure(text="Bir uygulama seçin")
        self.selected_app_meta.configure(
            text="İlişkili dosyalar seçiminizden sonra doğrulanır."
        )
        self.plan_table.set_rows([])
        self.plan_table.show_state(
            "Kaldırma planı bekliyor",
            "Soldaki listeden başka bir uygulama seçin.",
        )
        self.plan_detail.grid_remove()
        self.plan_summary.configure(text="")
        self.remove_button.configure(state="disabled")
        self._start_app_discovery()

    # ------------------------------------------------------------------
    # Orphan scanner
    # ------------------------------------------------------------------

    def _build_residue_tab(self, tab: ctk.CTkFrame) -> None:
        tab.configure(fg_color=SURFACE)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        intro = ctk.CTkFrame(
            tab,
            fg_color=BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=10,
        )
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 10))
        intro.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            intro,
            text="Eski kalıntıları inceleyin",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(13, 2))
        ctk.CTkLabel(
            intro,
            text=(
                "Yalnızca kimliği doğrulanabilen kalıntılar seçilebilir; isim "
                "benzerliğiyle bulunanlar inceleme için listelenir. Tarama "
                "/Applications ve ~/Applications ile sınırlıdır."
            ),
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=560,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 13))
        self.scan_button = self._primary_button(
            intro,
            "Taramayı Başlat",
            self._start_orphan_scan,
            width=154,
        )
        self.scan_button.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=16,
        )

        # Tam Disk Erişimi verilmemişse proaktif uyarı bandı (başta gizli).
        self.fda_banner = ctk.CTkFrame(intro, fg_color=WARNING_SOFT, corner_radius=8)
        self.fda_banner.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 13)
        )
        self.fda_banner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.fda_banner,
            text=(
                "⚠ Tam Disk Erişimi verilmemiş görünüyor; bazı korumalı konumlar "
                "(Containers, Group Containers) taranamayabilir."
            ),
            font=ctk.CTkFont(size=12),
            text_color=WARNING,
            anchor="w",
            justify="left",
            wraplength=520,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=8)
        self._secondary_button(
            self.fda_banner,
            "Ayarları Aç",
            self._open_full_disk_settings,
            width=120,
        ).grid(row=0, column=1, sticky="e", padx=12, pady=8)
        self.fda_banner.grid_remove()

        filters = ctk.CTkFrame(tab, fg_color="transparent")
        filters.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        filters.grid_columnconfigure(0, weight=1)
        self.orphan_search = ctk.CTkEntry(
            filters,
            placeholder_text="Aday, kategori veya yol ara",
            height=38,
            border_color=BORDER,
            fg_color=BG,
            text_color=TEXT,
            placeholder_text_color=MUTED,
        )
        self.orphan_search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.orphan_search.bind("<KeyRelease>", self._schedule_orphan_filter)
        self._secondary_button(
            filters,
            "Tümünü İşaretle",
            lambda: self.orphan_table.check_visible(True),
            width=140,
        ).grid(row=0, column=1, sticky="e", padx=(0, 6))
        self._secondary_button(
            filters,
            "Temizle",
            lambda: self.orphan_table.check_visible(False),
            width=88,
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))
        self.orphan_filter = ctk.CTkSegmentedButton(
            filters,
            values=["Tümü", "Seçilebilir", "Korunan"],
            command=lambda _value: self._render_orphans(),
            selected_color=PRIMARY,
            selected_hover_color=PRIMARY_HOVER,
            unselected_color=SURFACE_SUBTLE,
            unselected_hover_color=PRIMARY_SOFT,
            text_color=TEXT,
            height=38,
        )
        self.orphan_filter.grid(row=0, column=3, sticky="e")
        self.orphan_filter.set("Tümü")

        content = ctk.CTkFrame(tab, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=14)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.orphan_table: FastTable[OrphanItem] = self._table(
            content,
            columns=(
                TableColumn("name", "Aday", 260, stretch=True),
                TableColumn("category", "Kategori", 160),
                TableColumn("size", "Boyut", 95, anchor="e"),
                TableColumn("evidence", "Durum", 150),
            ),
            checkable=True,
            on_focus=self._show_orphan_detail,
            on_activate=self._show_orphan_detail,
            on_check_change=self._update_orphan_summary,
        )
        self.orphan_table.grid(row=0, column=0, sticky="nsew")
        self.orphan_table.show_state(
            "Tarama henüz başlamadı",
            "Kurulu uygulamaları ve kullanıcı Library klasörünü karşılaştırmak için taramayı başlatın.",
            action_label="Taramayı Başlat",
            action=self._start_orphan_scan,
        )
        self.orphan_detail = self._detail_panel(content)
        self.orphan_detail.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.orphan_detail.grid_remove()

        footer = ctk.CTkFrame(tab, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=14, pady=(10, 14))
        footer.grid_columnconfigure(0, weight=1)
        self.orphan_summary = ctk.CTkLabel(
            footer,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        self.orphan_summary.grid(row=0, column=0, sticky="w")
        # Belirsiz süreli işlem göstergesi (tarama sürerken görünür).
        self.orphan_progress = ctk.CTkProgressBar(
            footer, mode="indeterminate", width=150, height=6,
            progress_color=PRIMARY, fg_color=SURFACE_SUBTLE,
        )
        self.cleanup_button = self._destructive_button(
            footer,
            "Seçilenleri Çöp'e Taşı",
            self._confirm_cleanup,
            width=196,
        )
        self.cleanup_button.configure(state="disabled")
        self.cleanup_button.grid(row=0, column=2, sticky="e")

    def _schedule_orphan_filter(self, _event=None) -> None:
        if self._search_after:
            self.after_cancel(self._search_after)
        self._search_after = self.after(120, self._render_orphans)

    def _start_orphan_scan(self) -> None:
        self.scan_button.configure(state="disabled", text="Taranıyor")
        self.cleanup_button.configure(state="disabled")
        self.orphan_detail.grid_remove()
        self.orphan_table.show_state(
            "Tarama sürüyor",
            "Kurulu uygulamalar ve güvenli Library konumları karşılaştırılıyor.",
        )
        self.orphan_progress.grid(row=0, column=1, sticky="e", padx=8)
        self.orphan_progress.start()
        self._scan_generation += 1
        generation = self._scan_generation
        self._run_worker(lambda: self._orphan_scan_worker(generation))

    def _stop_orphan_progress(self) -> None:
        self.orphan_progress.stop()
        self.orphan_progress.grid_remove()

    def _orphan_scan_worker(self, generation: int) -> None:
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
                state_store=self.state_store,
                should_abort=lambda: generation != self._scan_generation,
            )
            if generation != self._scan_generation:
                return  # daha yeni bir tarama başladı; bu sonucu at

            combined = ScanReport(
                report.items,
                (*app_issues, *report.issues),
            )
            self._queue.put(("scan_done", (combined, apps)))
        except Exception as exc:  # noqa: BLE001
            self._report_worker_error("scan", exc)

    def _on_scan_done(self, payload) -> None:
        report, apps = payload
        self.orphan_report = report
        self.orphan_selected.clear()
        self.apps = apps
        self.state_store.update_inventory([app for app in apps if app.selectable])
        self.scan_button.configure(state="normal", text="Yeniden Tara")
        self._stop_orphan_progress()
        self._render_orphans()

    def _filtered_orphans(self) -> list[OrphanItem]:
        query = _normalize_query(self.orphan_search.get())
        filter_value = self.orphan_filter.get()
        items = list(self.orphan_report.items)
        if filter_value == "Seçilebilir":
            items = [item for item in items if item.selectable]
        elif filter_value == "Korunan":
            items = [item for item in items if not item.selectable]
        if query:
            items = [
                item
                for item in items
                if query
                in _normalize_query(
                    f"{item.display_name} {item.category.value} {item.path} {item.reason}"
                )
            ]
        return items

    def _render_orphans(self) -> None:
        self._sync_orphan_checked()
        items = self._filtered_orphans()
        rows = [
            TableRow(
                iid=f"orphan-{index}",
                cells=(
                    item.display_name,
                    item.category.value,
                    human_readable_size(item.size_bytes),
                    _evidence_label(item.evidence),
                ),
                payload=item,
                selectable=item.selectable,
                checked=item.path in self.orphan_selected,
                tone="warning" if not item.selectable else "normal",
                sort_values=(
                    item.display_name.casefold(),
                    item.category.value,
                    item.size_bytes if item.size_bytes is not None else -1,
                    _evidence_label(item.evidence),
                ),
            )
            for index, item in enumerate(items)
        ]
        self.orphan_table.set_rows(rows)
        if not self.orphan_report.items:
            self.orphan_table.show_state(
                "Temiz görünüyor",
                "İncelenecek eski kalıntı adayı bulunamadı.",
                action_label="Yeniden Tara",
                action=self._start_orphan_scan,
            )
            self.orphan_detail.grid_remove()
        elif not rows:
            self.orphan_table.show_state(
                "Filtreyle eşleşen aday yok",
                "Aramayı temizleyin veya farklı bir görünüm seçin.",
            )
            self.orphan_detail.grid_remove()
        self._update_orphan_summary()

    def _sync_orphan_checked(self) -> None:
        if not hasattr(self, "orphan_table"):
            return
        visible = {
            row.payload.path for row in self.orphan_table.model.rows.values()
        }
        checked = {item.path for item in self.orphan_table.checked_payloads()}
        self.orphan_selected.difference_update(visible)
        self.orphan_selected.update(checked)

    def _update_orphan_summary(self) -> None:
        self._sync_orphan_checked()
        selected_items = [
            item
            for item in self.orphan_report.items
            if item.path in self.orphan_selected
        ]
        total = sum(item.size_bytes or 0 for item in selected_items)
        issue_note = (
            f" · {len(self.orphan_report.issues)} okuma uyarısı"
            if self.orphan_report.issues
            else ""
        )
        self.orphan_summary.configure(
            text=(
                f"{len(self.orphan_report.items)} aday · "
                f"{len(selected_items)} seçili · "
                f"{human_readable_size(total)}{issue_note}"
                + (
                    ""
                    if selected_items
                    else " · Seçim sütununa tıklayın veya Space kullanın"
                )
            )
        )
        self.cleanup_button.configure(
            state="normal" if selected_items else "disabled"
        )

    def _show_orphan_detail(self, item: OrphanItem | None) -> None:
        if item is None:
            self.orphan_detail.grid_remove()
            return
        self._set_detail(
            self.orphan_detail,
            title=item.display_name,
            meta=(
                f"{item.category.value} · {human_readable_size(item.size_bytes)} · "
                f"{_date_label(item.last_modified)}"
            ),
            body=item.reason,
            path=item.path,
        )
        self.orphan_detail.grid()

    def _confirm_cleanup(self) -> None:
        self._sync_orphan_checked()
        if not self.orphan_selected:
            return
        selected = set(self.orphan_selected)
        self._confirm_dialog(
            "Seçilenleri Çöp'e taşı",
            f"{len(selected)} eski kalıntı adayı Çöp Kutusu'na taşınacak.",
            detail="Yollar ve dosya kimlikleri işlemden hemen önce yeniden doğrulanır.",
            action=lambda: self._start_cleanup(selected),
            trigger=self.cleanup_button,
        )

    def _start_cleanup(self, selected: set[Path]) -> None:
        self.cleanup_button.configure(state="disabled", text="Taşınıyor")
        items = self.orphan_report.items
        self._run_worker(lambda: self._cleanup_worker(items, selected))

    def _cleanup_worker(self, items, selected: set[Path]) -> None:
        try:
            result = cleanup.cleanup_orphans(items, selected)
            self._queue.put(("cleanup_done", result))
        except Exception as exc:  # noqa: BLE001
            self._report_worker_error("cleanup", exc)

    def _on_cleanup_done(self, result) -> None:
        self.cleanup_button.configure(text="Seçilenleri Çöp'e Taşı")
        moved = set(result.moved_paths)
        moved_items = [
            item for item in self.orphan_report.items if item.path in moved
        ]
        freed = human_readable_size(
            sum(item.size_bytes or 0 for item in moved_items)
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
            tuple(
                item
                for item in self.orphan_report.items
                if item.path not in moved
            ),
            self.orphan_report.issues,
        )
        self.orphan_selected.difference_update(moved)
        self._render_orphans()
        self._show_message(
            "Temizlik sonucu",
            banner,
            error=bool(result.failed_paths),
            recovery=(
                "Taşınamayan öğeleri yeniden tarayıp izinlerini kontrol edin."
                if result.failed_paths
                else "İsterseniz Çöp Kutusu'ndan geri yükleyebilirsiniz."
            ),
        )

    # ------------------------------------------------------------------
    # Queue and states
    # ------------------------------------------------------------------

    def _report_worker_error(self, kind: str, exc: Exception) -> None:
        """Worker istisnasını izlenebilir biçimde loglar ve UI'ya iletir."""
        logger.exception("%s worker hatası", kind)
        self._queue.put((f"{kind}_error", str(exc)))

    def _run_worker(self, target) -> None:
        self._worker_count += 1

        def wrapped() -> None:
            try:
                target()
            finally:
                self._queue.put(("worker_finished", None))

        threading.Thread(target=wrapped, daemon=True).start()
        if not self._polling:
            self._polling = True
            self.after(50, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "apps_done":
                    self._on_apps_done(payload)
                elif kind == "apps_error":
                    self._on_apps_error(payload)
                elif kind == "plan_done":
                    self._render_removal_plan(payload)
                elif kind == "plan_error":
                    self._on_plan_error(payload)
                elif kind == "removal_done":
                    self._on_removal_done(payload)
                elif kind == "removal_error":
                    self._on_removal_error(payload)
                elif kind == "scan_done":
                    self._on_scan_done(payload)
                elif kind == "scan_error":
                    self._on_scan_error(payload)
                elif kind == "cleanup_done":
                    self._on_cleanup_done(payload)
                elif kind == "cleanup_error":
                    self._on_cleanup_error(payload)
                elif kind == "worker_finished":
                    self._worker_count = max(0, self._worker_count - 1)
        except queue.Empty:
            pass
        if self._worker_count or not self._queue.empty():
            self.after(50, self._poll_queue)
        else:
            self._polling = False

    def _on_apps_error(self, message: str) -> None:
        self.refresh_apps_button.configure(state="normal", text="Yenile")
        self.app_table.set_rows([], focus_first=False)
        self.app_table.show_state(
            "Uygulamalar okunamadı",
            message,
            action_label="Yeniden Dene",
            action=self._start_app_discovery,
        )

    def _on_plan_error(self, message: str) -> None:
        self.remove_button.configure(state="disabled", text="Kaldırmayı Onayla")
        self.plan_table.set_rows([])
        self.plan_table.show_state(
            "Plan oluşturulamadı",
            message,
            action_label="Yeniden Dene",
            action=self._start_plan_build,
        )

    def _on_removal_error(self, message: str) -> None:
        self.remove_button.configure(state="normal", text="Kaldırmayı Onayla")
        self._show_message(
            "Kaldırma tamamlanamadı",
            message,
            error=True,
            recovery="Planı yeniden oluşturup tekrar deneyin.",
        )

    def _on_scan_error(self, message: str) -> None:
        self.scan_button.configure(state="normal", text="Yeniden Tara")
        self._stop_orphan_progress()
        self.orphan_table.set_rows([])
        self.orphan_table.show_state(
            "Tarama tamamlanamadı",
            message,
            action_label="Yeniden Dene",
            action=self._start_orphan_scan,
        )

    def _on_cleanup_error(self, message: str) -> None:
        self.cleanup_button.configure(
            state="normal" if self.orphan_selected else "disabled",
            text="Seçilenleri Çöp'e Taşı",
        )
        self._show_message(
            "Temizlik tamamlanamadı",
            message,
            error=True,
            recovery="Öğeleri yeniden tarayıp tekrar deneyin.",
        )

    # ------------------------------------------------------------------
    # Reusable UI
    # ------------------------------------------------------------------

    def _primary_button(self, master, text: str, command, *, width: int):
        button = ctk.CTkButton(
            master,
            text=text,
            command=command,
            width=width,
            height=40,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=("#FFFFFF", "#102013"),
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._bind_focus_ring(button, resting_width=0)
        return button

    def _secondary_button(self, master, text: str, command, *, width: int):
        button = ctk.CTkButton(
            master,
            text=text,
            command=command,
            width=width,
            height=40,
            fg_color=SURFACE_SUBTLE,
            hover_color=PRIMARY_SOFT,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._bind_focus_ring(button, resting_width=1)
        return button

    def _destructive_button(self, master, text: str, command, *, width: int):
        button = ctk.CTkButton(
            master,
            text=text,
            command=command,
            width=width,
            height=42,
            fg_color=DESTRUCTIVE,
            hover_color=DESTRUCTIVE_HOVER,
            text_color=("#FFFFFF", "#1E0F0B"),
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._bind_focus_ring(button, resting_width=0)
        return button

    @staticmethod
    def _bind_focus_ring(widget, *, resting_width: int) -> None:
        widget.bind(
            "<FocusIn>",
            lambda _event: widget.configure(
                border_width=2,
                border_color=WARNING,
            ),
        )
        widget.bind(
            "<FocusOut>",
            lambda _event: widget.configure(border_width=resting_width),
        )

    def _detail_panel(self, master) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(
            master,
            fg_color=BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=10,
            height=108,
        )
        panel.grid_columnconfigure(0, weight=1)
        title = ctk.CTkLabel(
            panel,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="ew", padx=14, pady=(11, 1))
        meta = ctk.CTkLabel(
            panel,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        )
        meta.grid(row=1, column=0, sticky="ew", padx=14)
        body = ctk.CTkLabel(
            panel,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=650,
        )
        body.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 10))
        finder = self._secondary_button(
            panel,
            "Finder'da Göster",
            lambda: None,
            width=132,
        )
        finder.grid(
            row=0,
            column=1,
            rowspan=3,
            sticky="e",
            padx=12,
        )
        panel._title_label = title
        panel._meta_label = meta
        panel._body_label = body
        panel._finder_button = finder
        return panel

    def _set_detail(
        self,
        panel,
        *,
        title: str,
        meta: str,
        body: str,
        path: Path,
    ) -> None:
        panel._title_label.configure(text=title)
        panel._meta_label.configure(text=f"{meta} · {_short_path(path, 88)}")
        panel._body_label.configure(text=body)
        panel._finder_button.configure(
            command=lambda target=path: self._reveal_in_finder(target)
        )

    def _confirm_dialog(
        self,
        title: str,
        message: str,
        *,
        detail: str,
        action,
        trigger,
    ) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        dialog.grab_set()
        card = ctk.CTkFrame(
            dialog,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=22, pady=(20, 6))
        ctk.CTkLabel(
            card,
            text=message,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT,
            justify="left",
            wraplength=440,
        ).pack(anchor="w", padx=22)
        ctk.CTkLabel(
            card,
            text=detail,
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            justify="left",
            wraplength=440,
        ).pack(anchor="w", padx=22, pady=(6, 18))
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(anchor="e", padx=18, pady=(0, 18))

        def close() -> None:
            dialog.grab_release()
            dialog.destroy()
            trigger.focus_set()

        def confirm() -> None:
            close()
            action()

        cancel = self._secondary_button(
            buttons,
            "İptal",
            close,
            width=112,
        )
        cancel.grid(row=0, column=0, padx=4)
        confirm_button = self._destructive_button(
            buttons,
            "Çöp'e Taşı",
            confirm,
            width=132,
        )
        confirm_button.grid(row=0, column=1, padx=4)
        dialog.bind("<Escape>", lambda _event: close())
        dialog.bind("<Return>", lambda _event: confirm())
        dialog.protocol("WM_DELETE_WINDOW", close)
        confirm_button.focus_set()
        self._size_dialog_to_content(dialog, card, min_width=520)
        self._center_dialog(dialog)

    def _show_message(
        self,
        title: str,
        message: str,
        *,
        error: bool = False,
        recovery: str = "",
    ) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        dialog.grab_set()
        card = ctk.CTkFrame(
            dialog,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=DESTRUCTIVE if error else PRIMARY,
        ).pack(anchor="w", padx=22, pady=(20, 6))
        ctk.CTkLabel(
            card,
            text=message,
            font=ctk.CTkFont(size=13),
            text_color=TEXT,
            justify="left",
            wraplength=460,
        ).pack(anchor="w", padx=22)
        if recovery:
            ctk.CTkLabel(
                card,
                text=recovery,
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
                justify="left",
                wraplength=460,
            ).pack(anchor="w", padx=22, pady=(8, 0))

        def close() -> None:
            dialog.grab_release()
            dialog.destroy()

        button = self._primary_button(card, "Tamam", close, width=120)
        button.pack(anchor="e", padx=22, pady=(18, 20))
        dialog.bind("<Escape>", lambda _event: close())
        dialog.bind("<Return>", lambda _event: close())
        dialog.protocol("WM_DELETE_WINDOW", close)
        button.focus_set()
        self._size_dialog_to_content(dialog, card, min_width=540)
        self._center_dialog(dialog)

    @staticmethod
    def _size_dialog_to_content(dialog, card, *, min_width: int) -> None:
        """Diyaloğu içeriğinin doğal boyutuna oturtur (uzun metinde kırpma olmaz)."""
        dialog.update_idletasks()
        width = max(min_width, card.winfo_reqwidth() + 36)
        height = card.winfo_reqheight() + 36
        dialog.geometry(f"{width}x{height}")

    def _center_dialog(self, dialog) -> None:
        self.update_idletasks()
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _reveal_in_finder(self, path: Path) -> None:
        try:
            subprocess.Popen(["open", "-R", str(path)])
        except OSError as exc:
            self._show_message(
                "Finder açılamadı",
                str(exc),
                error=True,
                recovery="Yolun hâlâ mevcut olduğunu kontrol edin.",
            )

    def _sync_native_theme(self) -> None:
        appearance = ctk.get_appearance_mode()
        if appearance != self._appearance:
            self._appearance = appearance
            for table in (
                self.app_table,
                self.plan_table,
                self.orphan_table,
            ):
                table.refresh_theme()
        self.after(1000, self._sync_native_theme)

    # ------------------------------------------------------------------
    # Native menu, keyboard shortcuts, Full Disk Access
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        app_menu = tk.Menu(menubar, tearoff=0)
        app_menu.add_command(label="maClean Hakkında", command=self._show_about)
        menubar.add_cascade(label="maClean", menu=app_menu)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label=".app Seç…", command=self._choose_external_app, accelerator="Cmd+O"
        )
        menubar.add_cascade(label="Dosya", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(
            label="Uygulama Kaldır",
            command=lambda: self.tabs.set("Uygulama Kaldır"),
            accelerator="Cmd+1",
        )
        view_menu.add_command(
            label="Eski Kalıntıları Tara",
            command=lambda: self.tabs.set("Eski Kalıntıları Tara"),
            accelerator="Cmd+2",
        )
        menubar.add_cascade(label="Görünüm", menu=view_menu)

        action_menu = tk.Menu(menubar, tearoff=0)
        action_menu.add_command(
            label="Uygulamaları Yenile",
            command=self._start_app_discovery,
            accelerator="Cmd+R",
        )
        action_menu.add_command(
            label="Kalıntı Taramasını Başlat",
            command=self._start_orphan_scan,
            accelerator="Cmd+Shift+R",
        )
        menubar.add_cascade(label="İşlem", menu=action_menu)

        try:
            self.configure(menu=menubar)
        except tk.TclError:
            logger.warning("Menü çubuğu kurulamadı", exc_info=True)

        self.bind_all("<Command-o>", lambda _e: self._choose_external_app())
        self.bind_all("<Command-r>", lambda _e: self._start_app_discovery())
        self.bind_all("<Command-R>", lambda _e: self._start_orphan_scan())
        self.bind_all("<Command-Key-1>", lambda _e: self.tabs.set("Uygulama Kaldır"))
        self.bind_all(
            "<Command-Key-2>", lambda _e: self.tabs.set("Eski Kalıntıları Tara")
        )
        self.bind_all("<Command-f>", self._focus_active_search)
        self.bind_all("<Command-a>", self._select_all_active)

    def _focus_active_search(self, _event=None) -> str:
        """Cmd+F: aktif sekmenin arama kutusuna odaklanır."""
        if self.tabs.get() == "Eski Kalıntıları Tara":
            self.orphan_search.focus_set()
        else:
            self.app_search.focus_set()
        return "break"

    def _select_all_active(self, _event=None):
        """Cmd+A: kalıntı sekmesinde görünen seçilebilirleri toplu işaretler.

        Odak bir metin kutusundaysa müdahale etmez; oradaki Cmd+A varsayılan
        'tümünü seç' davranışını korur.
        """
        focused = self.focus_get()
        if focused is not None and focused.winfo_class() == "Entry":
            return None
        if self.tabs.get() == "Eski Kalıntıları Tara":
            self.orphan_table.check_visible(True)
        return "break"

    def _show_about(self) -> None:
        self._show_message(
            "maClean Hakkında",
            f"maClean {__version__}\nYerel, imzasız uygulama kaldırıcı.",
            recovery="Tüm işlemler Çöp Kutusu'na taşır; kalıcı silme yapılmaz.",
        )

    def _has_full_disk_access(self) -> bool:
        """TCC korumalı bir konumu listelemeyi deneyerek FDA'yı en iyi çabayla saptar.

        PermissionError yalnızca Tam Disk Erişimi verilmemişken oluşur; yol yoksa
        veya başka bir hata olursa banner gösterilmez (yanlış-pozitif olmaz).
        """
        probe = Path.home() / "Library" / "Application Support" / "com.apple.TCC"
        try:
            with os.scandir(probe):
                return True
        except PermissionError:
            return False
        except OSError:
            return True

    def _check_full_disk_access(self) -> None:
        if not self._has_full_disk_access():
            self.fda_banner.grid()

    def _open_full_disk_settings(self) -> None:
        try:
            subprocess.Popen(
                [
                    "open",
                    "x-apple.systempreferences:com.apple.preference.security"
                    "?Privacy_AllFiles",
                ]
            )
        except OSError:
            logger.warning("Sistem Ayarları açılamadı", exc_info=True)
