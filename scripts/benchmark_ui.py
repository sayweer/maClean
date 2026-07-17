"""Repeatable GUI render benchmark for large result sets."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maclean.gui import App
from maclean.models import (
    EvidenceLevel,
    OrphanItem,
    ResidueCategory,
    ScanReport,
)


def count_widgets(widget) -> int:
    return 1 + sum(count_widgets(child) for child in widget.winfo_children())


def run(rows: int) -> tuple[float, int]:
    App._start_app_discovery = lambda self: None
    app = App()
    app.withdraw()
    app.orphan_report = ScanReport(
        tuple(
            OrphanItem(
                display_name=f"Example App {index}",
                bundle_id=f"com.example.app{index}",
                category=ResidueCategory.CACHE,
                path=Path(
                    f"/Users/example/Library/Caches/com.example.app{index}"
                ),
                size_bytes=1024 * (index + 1),
                last_modified=datetime.now(),
                evidence=EvidenceLevel.EXACT_IDENTIFIER,
                selectable=True,
                reason=(
                    "Kimlik biçimi eşleşiyor; kullanıcı incelemesi gerekiyor."
                ),
            )
            for index in range(rows)
        )
    )
    started = time.perf_counter()
    app._render_orphans()
    app.update_idletasks()
    elapsed_ms = (time.perf_counter() - started) * 1000
    widget_count = count_widgets(app.orphan_table)
    app.destroy()
    return elapsed_ms, widget_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=200)
    parser.add_argument("--max-render-ms", type=float, default=250)
    parser.add_argument("--max-widgets", type=int, default=50)
    args = parser.parse_args()

    elapsed_ms, widget_count = run(args.rows)
    print(
        f"rows={args.rows} render_ms={elapsed_ms:.2f} "
        f"widget_count={widget_count}"
    )
    if elapsed_ms > args.max_render_ms:
        raise SystemExit(
            f"render budget exceeded: {elapsed_ms:.2f}ms > "
            f"{args.max_render_ms}ms"
        )
    if widget_count > args.max_widgets:
        raise SystemExit(
            f"widget budget exceeded: {widget_count} > {args.max_widgets}"
        )


if __name__ == "__main__":
    main()
