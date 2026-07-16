"""maClean alan modelleri.

Modeller GUI'den ve dosya sistemi işlemlerinden bağımsız tutulur. Böylece
tarama/kaldırma kararları arayüz açılmadan test edilebilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class ResidueCategory(Enum):
    CACHE = "Cache"
    APPLICATION_SUPPORT = "Application Support"
    PREFERENCES = "Preferences"
    LOGS = "Logs"
    SAVED_STATE = "Saved Application State"
    CONTAINERS = "Containers"
    GROUP_CONTAINERS = "Group Containers"
    WEBKIT = "WebKit"
    HTTP_STORAGES = "HTTPStorages"
    APPLICATION_SCRIPTS = "Application Scripts"


class MatchConfidence(Enum):
    """Eski API ile uyumlu, kullanıcıya kesinlik iddiası taşımayan eşleşme türü."""

    BUNDLE_ID = "bundle_id"
    NAME_FUZZY = "name_fuzzy"


class EvidenceLevel(Enum):
    EXPLICIT_REMOVAL = "explicit_removal"
    OBSERVED_MISSING = "observed_missing"
    EXACT_IDENTIFIER = "exact_identifier"
    NAME_ONLY = "name_only"
    SHARED_OR_UNKNOWN = "shared_or_unknown"


class RemovalMode(Enum):
    STANDARD = "standard"
    FULL = "full"


class DataKind(Enum):
    APPLICATION = "application"
    TRANSIENT = "transient"
    PERSISTENT = "persistent"
    SHARED = "shared"


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    modified_ns: int


@dataclass(frozen=True)
class ScanIssue:
    path: Path
    message: str
    kind: str = "access"


@dataclass(frozen=True)
class ApplicationRecord:
    bundle_id: str
    name: str
    path: Path
    helper_bundle_ids: tuple[str, ...] = ()
    application_groups: tuple[str, ...] = ()
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    selectable: bool = True

    @property
    def all_bundle_ids(self) -> frozenset[str]:
        return frozenset((self.bundle_id, *self.helper_bundle_ids))


@dataclass
class OrphanItem:
    display_name: str
    bundle_id: str | None
    category: ResidueCategory
    path: Path
    size_bytes: int | None
    last_modified: datetime
    confidence: MatchConfidence
    evidence: EvidenceLevel = EvidenceLevel.EXACT_IDENTIFIER
    selectable: bool = False
    reason: str = ""
    identity: FileIdentity | None = None


@dataclass(frozen=True)
class ScanReport:
    items: tuple[OrphanItem, ...]
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True)
class RemovalItem:
    display_name: str
    path: Path
    category: ResidueCategory | None
    size_bytes: int | None
    last_modified: datetime
    evidence: EvidenceLevel
    data_kind: DataKind
    reason: str
    identity: FileIdentity | None
    selected_by_default: bool
    selectable: bool
    protected_reason: str | None = None


@dataclass(frozen=True)
class RemovalPlan:
    application: ApplicationRecord
    mode: RemovalMode
    application_identity: FileIdentity
    items: tuple[RemovalItem, ...]
    issues: tuple[ScanIssue, ...] = ()

    @property
    def default_selected_paths(self) -> frozenset[Path]:
        return frozenset(
            item.path
            for item in self.items
            if item.selectable and item.selected_by_default
        )


@dataclass(frozen=True)
class RemovalResult:
    application_moved: bool
    moved_paths: tuple[Path, ...] = ()
    failed_paths: tuple[tuple[Path, str], ...] = ()
    aborted_reason: str | None = None


@dataclass(frozen=True)
class CleanupResult:
    moved_paths: tuple[Path, ...] = ()
    failed_paths: tuple[tuple[Path, str], ...] = ()


def file_identity(path: Path) -> FileIdentity | None:
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return None
    return FileIdentity(
        device=stat.st_dev,
        inode=stat.st_ino,
        mode=stat.st_mode,
        modified_ns=stat.st_mtime_ns,
    )


def identity_matches(path: Path, expected: FileIdentity) -> bool:
    return file_identity(path) == expected


def human_readable_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "Bilinmiyor"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


FULL_DISK_ACCESS_CATEGORIES = frozenset(
    {ResidueCategory.CONTAINERS, ResidueCategory.GROUP_CONTAINERS}
)


def build_trash_banner(
    succeeded_count: int,
    freed: str,
    failed_items: list[OrphanItem],
    failure_messages: list[str] | None = None,
) -> str:
    """Çöp işlemi için doğru başarı/başarısızlık özeti üretir."""

    lines: list[str] = []
    if succeeded_count:
        lines.append(
            f"✓ {succeeded_count} öğe Çöp Kutusu'na taşındı · {freed} boşaltıldı."
        )
    elif failed_items:
        lines.append("⚠ Hiçbir öğe Çöp Kutusu'na taşınamadı.")
    else:
        lines.append("Taşınacak öğe bulunamadı.")

    if failed_items:
        lines.append(f"⚠ {len(failed_items)} öğe taşınamadı.")
        tcc_count = sum(
            item.category in FULL_DISK_ACCESS_CATEGORIES for item in failed_items
        )
        generic_count = len(failed_items) - tcc_count
        if tcc_count:
            lines.append(
                f"⚠ {tcc_count} korumalı öğe için Tam Disk Erişimi gerekiyor: "
                "Sistem Ayarları → Gizlilik ve Güvenlik → Tam Disk Erişimi."
            )
        if generic_count:
            lines.append(
                f"⚠ {generic_count} öğe izin, erişim veya değişiklik nedeniyle taşınamadı."
            )
        if failure_messages:
            unique = list(dict.fromkeys(message for message in failure_messages if message))
            if unique:
                lines.append("Ayrıntı: " + " · ".join(unique[:3]))
    return "\n".join(lines)
