"""Veri modelleri: kategori/güven enum'ları ve OrphanItem dataclass.

Bu modül paketin en alt katmanıdır — sadece standart kütüphaneye bağımlıdır,
paket içindeki hiçbir modülü import etmez.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class ResidueCategory(Enum):
    """Bir kalıntının bulunduğu ~/Library alt konumu.

    Değer, kullanıcıya (ve loglara) gösterilen okunabilir etikettir.
    """

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
    """Bir kalıntının "öksüz" olduğuna dair eşleştirme güveni."""

    BUNDLE_ID = "bundle_id"    # Kesin: ad doğrudan bundle-id desenindeydi
    NAME_FUZZY = "name_fuzzy"  # Tahmini: uygulama adına göre bulanık eşleşme


@dataclass
class OrphanItem:
    """Silinmiş bir uygulamaya ait olduğu düşünülen tek bir kalıntı öğe."""

    display_name: str
    bundle_id: str | None
    category: ResidueCategory
    path: Path
    size_bytes: int
    last_modified: datetime
    confidence: MatchConfidence
    selected: bool = False  # GUI checkbox durumu; güvenlik gereği varsayılan KAPALI


def human_readable_size(size_bytes: int) -> str:
    """Bayt sayısını okunabilir birime çevirir (ör. 1536 -> '1.5 KB').

    1024 tabanlı (binary) birimler kullanır; macOS Finder ondalık (1000
    tabanlı) gösterir, ancak burada bir öğenin kabaca ne kadar yer kapladığını
    iletmek yeterlidir — birebir Finder eşleşmesi hedeflenmez.
    """
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # erişilemez; tip denetleyicisi için
