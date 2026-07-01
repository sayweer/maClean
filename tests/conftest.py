"""Testler için ortak fixture'lar: sahte .app bundle'ları ve ~/Library kalıntıları.

Gerçek dosya sistemine dokunulmaz — her şey pytest'in tmp_path'i altında kurulur.
"""

import plistlib
from pathlib import Path

import pytest


def _make_app_bundle(
    apps_root: Path,
    rel_path: str,
    bundle_id: str | None,
    name: str | None = None,
) -> Path:
    """apps_root altında geçerli bir .app bundle iskeleti oluşturur.

    bundle_id None ise Info.plist CFBundleIdentifier alanı olmadan yazılır
    (kimliksiz/bozuk uygulama senaryosunu test etmek için).
    """
    app_dir = apps_root / rel_path
    contents = app_dir / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    info: dict[str, str] = {}
    if bundle_id is not None:
        info["CFBundleIdentifier"] = bundle_id
    if name is not None:
        info["CFBundleName"] = name
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    return app_dir


@pytest.fixture
def app_bundle_factory():
    """Sahte .app bundle oluşturan bir fabrika döndürür.

    Kullanım: app_bundle_factory(apps_root, "Foo.app", "com.foo.bar", "Foo")
    """
    return _make_app_bundle


def _make_residue(
    library_root: Path,
    location_name: str,
    entry_name: str,
    is_dir: bool = True,
    size: int = 0,
) -> Path:
    """library_root/<location_name>/<entry_name> altında sahte bir kalıntı kurar.

    entry_name '/' içerebilir (ör. "Adobe/Photoshop") — vendor şemsiye
    senaryolarını kurmak için. size>0 ise içine o boyutta veri yazılır.
    """
    location = library_root / location_name
    target = location / entry_name
    if is_dir:
        target.mkdir(parents=True, exist_ok=True)
        if size:
            (target / "data.bin").write_bytes(b"\0" * size)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\0" * size)
    return target


@pytest.fixture
def residue_factory():
    """Sahte ~/Library kalıntısı oluşturan bir fabrika döndürür."""
    return _make_residue
