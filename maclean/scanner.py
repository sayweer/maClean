"""Güvenlik-öncelikli eski kalıntı taraması."""

from __future__ import annotations

import logging
import os
import plistlib
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable

from . import constants
from .models import (
    EvidenceLevel,
    MatchConfidence,
    OrphanItem,
    ResidueCategory,
    ScanIssue,
    ScanReport,
    file_identity,
)
from .state import StateStore

logger = logging.getLogger(__name__)
RECENT_GRACE_PERIOD = timedelta(days=30)
UNSAFE_LEGACY_CATEGORIES = frozenset(
    {ResidueCategory.GROUP_CONTAINERS, ResidueCategory.APPLICATION_SCRIPTS}
)
_NON_ALNUM = re.compile(r"[^\w]+", re.UNICODE)


def _read_bundle(app_path: Path) -> tuple[str, str] | None:
    try:
        with (app_path / "Contents" / "Info.plist").open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        logger.warning("Info.plist okunamadı: %s (%s)", app_path, exc)
        return None
    bundle_id = plist.get("CFBundleIdentifier")
    if not isinstance(bundle_id, str) or not bundle_id:
        return None
    name = (
        plist.get("CFBundleDisplayName")
        or plist.get("CFBundleName")
        or app_path.name.removesuffix(".app")
    )
    return bundle_id.casefold(), str(name)


def discover_installed_apps(
    app_scan_roots: list[Path] | None = None,
) -> tuple[set[str], dict[str, str]]:
    roots = constants.APP_SCAN_ROOTS if app_scan_roots is None else app_scan_roots
    installed_ids: set[str] = set()
    name_by_id: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, _ in os.walk(root):
            app_dirs = [name for name in dirnames if name.casefold().endswith(".app")]
            dirnames[:] = [
                name for name in dirnames if not name.casefold().endswith(".app")
            ]
            for app_dir in app_dirs:
                result = _read_bundle(Path(dirpath) / app_dir)
                if result:
                    bundle_id, name = result
                    installed_ids.add(bundle_id)
                    name_by_id[bundle_id] = name
    return installed_ids, name_by_id


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return _NON_ALNUM.sub("", without_marks)


def _strip_suffixes(name: str) -> str:
    lowered = name.casefold()
    for suffix in constants.STRIP_SUFFIXES:
        if lowered.endswith(suffix.casefold()):
            return name[: -len(suffix)]
    return name


def _looks_like_version(text: str) -> bool:
    return any(segment.isdigit() for segment in text.split("."))


def _prettify_bundle_id(bundle_id: str) -> str:
    last = bundle_id.split(".")[-1]
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", last)
    return spaced.replace("-", " ").replace("_", " ").strip() or bundle_id


def _is_protected_identifier(identifier: str) -> bool:
    lowered = identifier.casefold()
    return (
        lowered.startswith("com.apple.")
        or lowered.startswith("group.com.apple.")
        or lowered.startswith("systemgroup.com.apple.")
        or ".com.apple." in lowered
        or ".groups.com.apple." in lowered
    )


def _safe_entries(path: Path, issues: list[ScanIssue]) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as iterator:
            return list(iterator)
    except OSError as exc:
        issues.append(ScanIssue(path, str(exc), "access"))
        return []


def _measure_path(path: Path, issues: list[ScanIssue]) -> int | None:
    if path.is_symlink():
        return None
    try:
        if path.is_file():
            return path.stat(follow_symlinks=False).st_size
    except OSError as exc:
        issues.append(ScanIssue(path, str(exc), "size"))
        return None

    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except OSError as exc:
            issues.append(ScanIssue(current, str(exc), "size"))
            return None
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
            except OSError as exc:
                issues.append(ScanIssue(Path(entry.path), str(exc), "size"))
                return None
    return total


def measure_path(path: Path) -> tuple[int | None, tuple[ScanIssue, ...]]:
    issues: list[ScanIssue] = []
    return _measure_path(path, issues), tuple(issues)


def _fuzzy_matches(candidate: str, installed_norms: set[str]) -> bool:
    norm = _normalize(candidate)
    if not norm:
        return True
    return any(
        norm == installed
        or SequenceMatcher(None, norm, installed).ratio()
        >= constants.FUZZY_MATCH_THRESHOLD
        for installed in installed_norms
        if installed
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def scan_orphans(
    installed_ids: set[str],
    installed_names: Iterable[str],
    library_root: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
    state_store: StateStore | None = None,
    now: datetime | None = None,
) -> ScanReport:
    lib_root = library_root or constants.LIBRARY_ROOT
    current_time = now or datetime.now()
    installed_norms = {_normalize(name) for name in installed_names}
    issues: list[ScanIssue] = []
    items: list[OrphanItem] = []
    store = state_store or StateStore()

    for category, default_path in constants.SCAN_LOCATIONS.items():
        if category in UNSAFE_LEGACY_CATEGORIES:
            continue
        if progress_callback:
            progress_callback(category.value)
        location = lib_root / default_path.name
        if not location.is_dir():
            continue
        expanded_entries: list[tuple[os.DirEntry, str | None]] = []
        for entry in _safe_entries(location, issues):
            is_umbrella = (
                category in constants.NAME_FUZZY_LOCATIONS
                and entry.name.casefold() in constants.VENDOR_UMBRELLA_FOLDERS
            )
            try:
                umbrella_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                umbrella_dir = False
            if is_umbrella and umbrella_dir:
                expanded_entries.extend(
                    (subentry, entry.name)
                    for subentry in _safe_entries(Path(entry.path), issues)
                )
            else:
                expanded_entries.append((entry, None))

        for entry, vendor_prefix in expanded_entries:
            path = Path(entry.path)
            if entry.is_symlink() or not _inside(path, lib_root):
                continue
            name = _strip_suffixes(entry.name)
            lowered = name.casefold()
            if entry.name.casefold() in constants.KNOWN_TOOL_CACHES:
                continue
            alias = constants.KNOWN_APP_DATA_ALIASES.get(entry.name.casefold())
            if alias and alias in installed_ids:
                continue

            bundle_like = bool(
                constants.BUNDLE_ID_PATTERN.fullmatch(name)
                and not _looks_like_version(name)
            )
            bundle_id: str | None = lowered if bundle_like else None
            if bundle_id and _is_protected_identifier(bundle_id):
                continue
            if bundle_id and (
                bundle_id in installed_ids
                or any(bundle_id.startswith(app_id + ".") for app_id in installed_ids)
            ):
                continue
            if bundle_id and _fuzzy_matches(name, installed_norms):
                continue
            if not bundle_like:
                if category not in constants.NAME_FUZZY_LOCATIONS:
                    continue
                names_to_check = [name]
                if vendor_prefix:
                    names_to_check.append(f"{vendor_prefix} {name}")
                if any(_fuzzy_matches(candidate, installed_norms) for candidate in names_to_check):
                    continue

            try:
                modified = datetime.fromtimestamp(
                    entry.stat(follow_symlinks=False).st_mtime
                )
            except OSError as exc:
                issues.append(ScanIssue(path, str(exc), "stat"))
                modified = datetime.fromtimestamp(0)
            size = _measure_path(path, issues)
            recent = modified >= current_time - RECENT_GRACE_PERIOD

            if bundle_id:
                evidence = store.evidence_for(bundle_id, installed_ids)
                confidence = MatchConfidence.BUNDLE_ID
                display_name = _prettify_bundle_id(name)
                reason = {
                    EvidenceLevel.EXPLICIT_REMOVAL:
                        "maClean bu uygulamayı daha önce kaldırdı.",
                    EvidenceLevel.OBSERVED_MISSING:
                        "Uygulama daha önce görülmüştü, artık bulunamıyor.",
                    EvidenceLevel.EXACT_IDENTIFIER:
                        "Ad bundle kimliği biçiminde; uygulama kurulu listede bulunamadı.",
                }[evidence]
            else:
                evidence = EvidenceLevel.NAME_ONLY
                confidence = MatchConfidence.NAME_FUZZY
                display_name = (
                    f"{vendor_prefix} — {name}" if vendor_prefix else name
                )
                reason = "Ad kurulu uygulamalarla eşleşmedi; sahiplik doğrulanamadı."

            selectable = (
                size is not None
                and not recent
                and evidence
                in {
                    EvidenceLevel.EXPLICIT_REMOVAL,
                    EvidenceLevel.OBSERVED_MISSING,
                    EvidenceLevel.EXACT_IDENTIFIER,
                    EvidenceLevel.NAME_ONLY,
                }
            )
            if recent and evidence is not EvidenceLevel.EXPLICIT_REMOVAL:
                reason += " Son 30 günde değiştiği için seçim devre dışı."
            if size is None:
                reason += " Boyutu okunamadığı için seçim devre dışı."

            items.append(
                OrphanItem(
                    display_name=display_name,
                    bundle_id=bundle_id,
                    category=category,
                    path=path,
                    size_bytes=size,
                    last_modified=modified,
                    confidence=confidence,
                    evidence=evidence,
                    selectable=selectable,
                    reason=reason,
                    identity=file_identity(path),
                )
            )
    items.sort(key=lambda item: item.size_bytes or -1, reverse=True)
    return ScanReport(tuple(items), tuple(issues))


def find_orphans(
    installed_ids: set[str],
    installed_names: Iterable[str],
    library_root: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> list[OrphanItem]:
    """Eski çağıranlar için liste döndüren uyumluluk sarmalayıcısı."""

    return list(
        scan_orphans(
            installed_ids,
            installed_names,
            library_root=library_root,
            progress_callback=progress_callback,
        ).items
    )
