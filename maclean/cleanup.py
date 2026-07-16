"""Eski kalıntıları taşıma öncesi yeniden doğrulayan servis."""

from __future__ import annotations

from pathlib import Path

from . import constants, trash
from .models import CleanupResult, OrphanItem, identity_matches


def cleanup_orphans(
    items: list[OrphanItem] | tuple[OrphanItem, ...],
    selected_paths: set[Path] | frozenset[Path],
    *,
    library_root: Path | None = None,
) -> CleanupResult:
    root = (library_root or constants.LIBRARY_ROOT).resolve()
    moved: list[Path] = []
    failed: list[tuple[Path, str]] = []

    for item in items:
        if item.path not in selected_paths or not item.selectable:
            continue
        try:
            resolved = item.path.resolve()
        except OSError:
            failed.append((item.path, "Yol artık doğrulanamıyor."))
            continue
        if item.path.is_symlink() or not resolved.is_relative_to(root):
            failed.append((item.path, "Güvenli tarama kökü dışındaki yol atlandı."))
            continue
        if item.identity is None or not identity_matches(item.path, item.identity):
            failed.append((item.path, "Öğe taramadan sonra değişti; yeniden tarayın."))
            continue
        succeeded, item_failed = trash.move_to_trash([item.path])
        moved.extend(succeeded)
        failed.extend(item_failed)

    return CleanupResult(tuple(moved), tuple(failed))
