"""Kurulu macOS uygulamalarını keşfetme ve güvenli biçimde tanımlama."""

from __future__ import annotations

import os
import plistlib
import subprocess
from datetime import datetime
from pathlib import Path

from .models import ApplicationRecord, ScanIssue

HOME = Path.home()
SELECTABLE_ROOTS = (Path("/Applications"), HOME / "Applications")
PROTECTOR_ROOTS = (
    Path("/System/Applications"),
    Path("/System/Library/CoreServices"),
    Path("/Library/CoreServices"),
)
SELF_BUNDLE_ID = "com.seyit.maclean"
NESTED_BUNDLE_SUFFIXES = (".app", ".appex", ".xpc")


class ApplicationError(ValueError):
    pass


def _read_info(path: Path) -> dict:
    info_path = path / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ApplicationError(f"Info.plist okunamadı: {exc}") from exc
    if not isinstance(info, dict):
        raise ApplicationError("Info.plist geçerli bir sözlük değil.")
    return info


def _bundle_identity(path: Path) -> tuple[str, str]:
    info = _read_info(path)
    bundle_id = info.get("CFBundleIdentifier")
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        raise ApplicationError("Uygulamanın CFBundleIdentifier değeri yok.")
    name = (
        info.get("CFBundleDisplayName")
        or info.get("CFBundleName")
        or path.name.removesuffix(".app")
    )
    return bundle_id.casefold(), str(name)


def _nested_bundle_ids(app_path: Path) -> tuple[str, ...]:
    ids: set[str] = set()
    for dirpath, dirnames, _ in os.walk(app_path):
        current = Path(dirpath)
        if current != app_path and current.name.endswith(NESTED_BUNDLE_SUFFIXES):
            try:
                bundle_id, _ = _bundle_identity(current)
            except ApplicationError:
                pass
            else:
                ids.add(bundle_id)
            dirnames[:] = []
    return tuple(sorted(ids))


def _application_groups(app_path: Path) -> tuple[str, ...]:
    """Entitlement XML okunamazsa güvenli biçimde boş küme döndürür."""

    try:
        proc = subprocess.run(
            [
                "codesign",
                "--display",
                "--entitlements",
                "-",
                "--xml",
                str(app_path),
            ],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()

    data = proc.stdout + proc.stderr
    starts = [index for marker in (b"<?xml", b"<plist", b"bplist00")
              if (index := data.find(marker)) >= 0]
    if not starts:
        return ()
    try:
        entitlements = plistlib.loads(data[min(starts):])
    except Exception:
        return ()
    groups = entitlements.get("com.apple.security.application-groups", [])
    if not isinstance(groups, list):
        return ()
    return tuple(sorted({str(group).casefold() for group in groups}))


def read_application(
    path: Path,
    *,
    selectable: bool = True,
    include_entitlements: bool = False,
) -> ApplicationRecord:
    path = path.expanduser()
    if path.is_symlink():
        raise ApplicationError("Sembolik link uygulamalar kaldırılamaz.")
    if path.suffix.casefold() != ".app" or not path.is_dir():
        raise ApplicationError("Seçilen yol geçerli bir .app paketi değil.")
    resolved = path.resolve()
    bundle_id, name = _bundle_identity(resolved)
    groups = _application_groups(resolved) if include_entitlements else ()
    return ApplicationRecord(
        bundle_id=bundle_id,
        name=name,
        path=resolved,
        helper_bundle_ids=_nested_bundle_ids(resolved),
        application_groups=groups,
        selectable=selectable,
    )


def enrich_application_groups(app: ApplicationRecord) -> ApplicationRecord:
    return ApplicationRecord(
        bundle_id=app.bundle_id,
        name=app.name,
        path=app.path,
        helper_bundle_ids=app.helper_bundle_ids,
        application_groups=_application_groups(app.path),
        first_seen=app.first_seen,
        last_seen=app.last_seen,
        selectable=app.selectable,
    )


def _discover_root(
    root: Path,
    *,
    selectable: bool,
) -> tuple[list[ApplicationRecord], list[ScanIssue]]:
    apps: list[ApplicationRecord] = []
    issues: list[ScanIssue] = []
    if not root.exists():
        return apps, issues

    def onerror(error: OSError) -> None:
        issues.append(ScanIssue(Path(error.filename or root), str(error), "app_scan"))

    for dirpath, dirnames, _ in os.walk(root, onerror=onerror):
        app_dirs = [name for name in dirnames if name.casefold().endswith(".app")]
        dirnames[:] = [name for name in dirnames if not name.casefold().endswith(".app")]
        for app_dir in app_dirs:
            path = Path(dirpath) / app_dir
            try:
                apps.append(read_application(path, selectable=selectable))
            except ApplicationError as exc:
                issues.append(ScanIssue(path, str(exc), "bundle"))
    return apps, issues


def discover_applications(
    selectable_roots: tuple[Path, ...] = SELECTABLE_ROOTS,
    protector_roots: tuple[Path, ...] = PROTECTOR_ROOTS,
) -> tuple[list[ApplicationRecord], list[ScanIssue]]:
    records: dict[tuple[str, Path], ApplicationRecord] = {}
    issues: list[ScanIssue] = []
    for root in selectable_roots:
        found, found_issues = _discover_root(root, selectable=True)
        issues.extend(found_issues)
        records.update({(app.bundle_id, app.path): app for app in found})
    for root in protector_roots:
        found, found_issues = _discover_root(root, selectable=False)
        issues.extend(found_issues)
        records.update({(app.bundle_id, app.path): app for app in found})
    return sorted(records.values(), key=lambda app: app.name.casefold()), issues


def validate_removable_application(app: ApplicationRecord) -> str | None:
    path = app.path.resolve()
    if app.bundle_id == SELF_BUNDLE_ID:
        return "maClean kendi kendisini kaldıramaz."
    if path.is_relative_to(Path("/System")):
        return "macOS sistem uygulamaları kaldırılamaz."
    if not app.selectable:
        return "Bu uygulama korumalı bir sistem konumunda."
    if app.path.is_symlink():
        return "Sembolik link uygulamalar kaldırılamaz."
    return None


def is_application_running(app: ApplicationRecord) -> bool:
    """Seçilen .app içinden çalışan bir executable varsa True döndürür."""

    executable_root = str(app.path / "Contents" / "MacOS")
    try:
        proc = subprocess.run(
            ["ps", "-axo", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Çalışma durumu doğrulanamıyorsa güvenlik gereği kaldırmayı engelle.
        return True
    return any(executable_root in line for line in proc.stdout.splitlines())
