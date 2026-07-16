"""High-performance native table components used by the CustomTkinter shell."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar
from tkinter import ttk

import customtkinter as ctk

T = TypeVar("T")
ColorToken = str | tuple[str, str]


def resolved_color(token: ColorToken) -> str:
    if isinstance(token, str):
        return token
    return token[1] if ctk.get_appearance_mode() == "Dark" else token[0]


@dataclass(frozen=True)
class TableColumn:
    key: str
    title: str
    width: int
    anchor: str = "w"
    stretch: bool = False


@dataclass(frozen=True)
class TableRow(Generic[T]):
    iid: str
    cells: tuple[str, ...]
    payload: T
    selectable: bool = True
    checked: bool = False
    tone: str = "normal"
    sort_values: tuple[object, ...] = ()


class TableModel(Generic[T]):
    """Selection state independent from Tk widgets."""

    def __init__(self) -> None:
        self.rows: dict[str, TableRow[T]] = {}
        self.order: list[str] = []
        self.checked: set[str] = set()

    def set_rows(self, rows: list[TableRow[T]]) -> None:
        self.rows = {row.iid: row for row in rows}
        self.order = [row.iid for row in rows]
        self.checked = {
            row.iid for row in rows if row.selectable and row.checked
        }

    def toggle(self, iid: str) -> bool:
        row = self.rows.get(iid)
        if row is None or not row.selectable:
            return False
        if iid in self.checked:
            self.checked.remove(iid)
        else:
            self.checked.add(iid)
        return True

    def checked_payloads(self) -> list[T]:
        return [
            self.rows[iid].payload
            for iid in self.order
            if iid in self.checked
        ]


class FastTable(ctk.CTkFrame, Generic[T]):
    """A single native Treeview instead of thousands of per-row CTk widgets."""

    def __init__(
        self,
        master,
        *,
        columns: tuple[TableColumn, ...],
        checkable: bool,
        on_focus: Callable[[T | None], None] | None = None,
        on_activate: Callable[[T], None] | None = None,
        on_check_change: Callable[[], None] | None = None,
        bg_color: ColorToken,
        surface_color: ColorToken,
        border_color: ColorToken,
        text_color: ColorToken,
        muted_color: ColorToken,
        accent_color: ColorToken,
        warning_color: ColorToken,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=surface_color,
            border_width=1,
            border_color=border_color,
            corner_radius=10,
            **kwargs,
        )
        self.columns = columns
        self.checkable = checkable
        self.on_focus = on_focus
        self.on_activate = on_activate
        self.on_check_change = on_check_change
        self.model: TableModel[T] = TableModel()
        self._sort_column: int | None = None
        self._sort_reverse = False
        self._tokens = {
            "bg": bg_color,
            "surface": surface_color,
            "border": border_color,
            "text": text_color,
            "muted": muted_color,
            "accent": accent_color,
            "warning": warning_color,
        }
        self._style_name = f"MaClean{str(id(self))}.Treeview"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        keys = ["__check__"] if checkable else []
        keys.extend(column.key for column in columns)
        self.tree = ttk.Treeview(
            self,
            columns=keys,
            show="headings",
            selectmode="browse",
            style=self._style_name,
            takefocus=True,
        )
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
        scrollbar = ctk.CTkScrollbar(
            self,
            command=self.tree.yview,
            width=12,
            fg_color="transparent",
            button_color=border_color,
            button_hover_color=accent_color,
        )
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(2, 3), pady=5)
        self.tree.configure(yscrollcommand=scrollbar.set)

        if checkable:
            self.tree.heading("__check__", text="")
            self.tree.column(
                "__check__", width=42, minwidth=42, stretch=False, anchor="center"
            )
        for index, column in enumerate(columns):
            self.tree.heading(
                column.key,
                text=column.title,
                command=lambda idx=index: self._sort(idx),
            )
            self.tree.column(
                column.key,
                width=column.width,
                minwidth=70,
                stretch=column.stretch,
                anchor=column.anchor,
            )

        self.tree.bind("<<TreeviewSelect>>", self._handle_focus)
        self.tree.bind("<Double-1>", self._handle_activate)
        self.tree.bind("<Return>", self._handle_activate)
        self.tree.bind("<space>", self._handle_space)
        self.tree.bind("<Button-1>", self._handle_click, add="+")
        self.tree.bind(
            "<FocusIn>",
            lambda _event: self.configure(
                border_color=accent_color,
                border_width=2,
            ),
        )
        self.tree.bind(
            "<FocusOut>",
            lambda _event: self.configure(
                border_color=border_color,
                border_width=1,
            ),
        )

        self.state_panel = ctk.CTkFrame(
            self,
            fg_color=surface_color,
            corner_radius=8,
        )
        self.state_title = ctk.CTkLabel(
            self.state_panel,
            text="",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=text_color,
        )
        self.state_title.pack(pady=(24, 4), padx=24)
        self.state_body = ctk.CTkLabel(
            self.state_panel,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=muted_color,
            wraplength=520,
            justify="center",
        )
        self.state_body.pack(pady=(0, 24), padx=24)
        self.state_button = ctk.CTkButton(
            self.state_panel,
            text="",
            height=40,
            fg_color=accent_color,
            hover_color=accent_color,
        )
        self._apply_style()

    def _apply_style(self) -> None:
        style = ttk.Style(self)
        style.configure(
            self._style_name,
            background=resolved_color(self._tokens["surface"]),
            fieldbackground=resolved_color(self._tokens["surface"]),
            foreground=resolved_color(self._tokens["text"]),
            borderwidth=0,
            relief="flat",
            rowheight=38,
            font=(".AppleSystemUIFont", 12),
        )
        style.configure(
            f"{self._style_name}.Heading",
            background=resolved_color(self._tokens["bg"]),
            foreground=resolved_color(self._tokens["muted"]),
            borderwidth=0,
            relief="flat",
            font=(".AppleSystemUIFont", 12, "bold"),
            padding=(8, 8),
        )
        style.map(
            self._style_name,
            background=[
                ("selected", resolved_color(self._tokens["bg"])),
            ],
            foreground=[
                ("selected", resolved_color(self._tokens["text"])),
            ],
        )
        self.tree.tag_configure(
            "normal",
            foreground=resolved_color(self._tokens["text"]),
        )
        self.tree.tag_configure(
            "muted",
            foreground=resolved_color(self._tokens["muted"]),
        )
        self.tree.tag_configure(
            "warning",
            foreground=resolved_color(self._tokens["warning"]),
        )
        self.tree.tag_configure(
            "checked",
            foreground=resolved_color(self._tokens["accent"]),
        )

    def refresh_theme(self) -> None:
        self._apply_style()

    def set_rows(
        self,
        rows: list[TableRow[T]],
        *,
        focus_first: bool = True,
    ) -> None:
        self.hide_state()
        self.model.set_rows(rows)
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in rows:
            self._insert(row)
        if rows and focus_first:
            self.tree.focus(rows[0].iid)
            self.tree.selection_set(rows[0].iid)
            self.tree.see(rows[0].iid)
            if self.on_focus:
                self.on_focus(rows[0].payload)

    def _insert(self, row: TableRow[T]) -> None:
        values: list[str] = []
        if self.checkable:
            if not row.selectable:
                values.append("—")
            else:
                values.append("✓" if row.iid in self.model.checked else "○")
        values.extend(row.cells)
        tag = "checked" if row.iid in self.model.checked else row.tone
        self.tree.insert("", "end", iid=row.iid, values=values, tags=(tag,))

    def show_state(
        self,
        title: str,
        body: str,
        *,
        action_label: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        self.state_title.configure(text=title)
        self.state_body.configure(text=body)
        if action_label and action:
            self.state_button.configure(text=action_label, command=action)
            self.state_button.pack(pady=(0, 24), padx=24)
        else:
            self.state_button.pack_forget()
        self.state_panel.place(relx=0.5, rely=0.5, anchor="center")
        self.state_panel.lift()

    def hide_state(self) -> None:
        self.state_panel.place_forget()

    def focused_payload(self) -> T | None:
        iid = self.tree.focus()
        row = self.model.rows.get(iid)
        return row.payload if row else None

    def checked_payloads(self) -> list[T]:
        return self.model.checked_payloads()

    def _handle_focus(self, _event=None) -> None:
        if self.on_focus:
            self.on_focus(self.focused_payload())

    def _handle_activate(self, _event=None):
        payload = self.focused_payload()
        if payload is not None and self.on_activate:
            self.on_activate(payload)
        return "break"

    def _handle_space(self, _event=None):
        if self.checkable:
            self._toggle(self.tree.focus())
        elif self.on_activate:
            self._handle_activate()
        return "break"

    def _handle_click(self, event):
        if not self.checkable:
            return None
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if row and column == "#1":
            self.tree.focus(row)
            self.tree.selection_set(row)
            self._toggle(row)
            return "break"
        return None

    def _toggle(self, iid: str) -> None:
        if not self.model.toggle(iid):
            return
        row = self.model.rows[iid]
        values = list(self.tree.item(iid, "values"))
        values[0] = "✓" if iid in self.model.checked else "○"
        tag = "checked" if iid in self.model.checked else row.tone
        self.tree.item(iid, values=values, tags=(tag,))
        if self.on_check_change:
            self.on_check_change()

    def _sort(self, column_index: int) -> None:
        if self._sort_column == column_index:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_index
            self._sort_reverse = False

        def value(iid: str):
            row = self.model.rows[iid]
            if row.sort_values and column_index < len(row.sort_values):
                return row.sort_values[column_index]
            return row.cells[column_index].casefold()

        self.model.order.sort(key=value, reverse=self._sort_reverse)
        for position, iid in enumerate(self.model.order):
            self.tree.move(iid, "", position)
