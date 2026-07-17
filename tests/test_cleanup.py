from datetime import datetime
from pathlib import Path

from maclean import cleanup
from maclean.models import (
    EvidenceLevel,
    OrphanItem,
    ResidueCategory,
    file_identity,
)


def _item(path: Path, selectable: bool = True) -> OrphanItem:
    return OrphanItem(
        display_name=path.name,
        bundle_id="com.example.old",
        category=ResidueCategory.CACHE,
        path=path,
        size_bytes=1,
        last_modified=datetime.now(),
        evidence=EvidenceLevel.EXACT_IDENTIFIER,
        selectable=selectable,
        identity=file_identity(path),
    )


def test_cleanup_revalidates_and_moves_selected_item(tmp_path, monkeypatch):
    library = tmp_path / "Library"
    path = library / "Caches" / "com.example.old"
    path.mkdir(parents=True)
    item = _item(path)
    calls = []

    monkeypatch.setattr(
        cleanup.trash,
        "move_to_trash",
        lambda paths: (calls.extend(paths) or list(paths), []),
    )

    result = cleanup.cleanup_orphans([item], {path}, library_root=library)

    assert result.moved_paths == (path,)
    assert calls == [path]


def test_cleanup_skips_changed_item(tmp_path, monkeypatch):
    library = tmp_path / "Library"
    path = library / "Caches" / "com.example.old"
    path.mkdir(parents=True)
    item = _item(path)
    path.touch()
    monkeypatch.setattr(
        cleanup.trash,
        "move_to_trash",
        lambda paths: (list(paths), []),
    )

    result = cleanup.cleanup_orphans([item], {path}, library_root=library)

    assert not result.moved_paths
    assert "değişti" in result.failed_paths[0][1]


def test_cleanup_ignores_unselectable_item(tmp_path, monkeypatch):
    library = tmp_path / "Library"
    path = library / "Caches" / "com.example.old"
    path.mkdir(parents=True)
    item = _item(path, selectable=False)
    monkeypatch.setattr(
        cleanup.trash,
        "move_to_trash",
        lambda _paths: (_ for _ in ()).throw(AssertionError("çağrılmamalı")),
    )

    result = cleanup.cleanup_orphans([item], {path}, library_root=library)
    assert not result.moved_paths
    assert not result.failed_paths
