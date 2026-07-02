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


# macOS'un TCC gizlilik koruması altındaki konumlar. Bu kategorilerdeki
# kalıntıları Çöp'e taşımak "Tam Disk Erişimi" izni gerektirir; izin yoksa
# taşıma yerelleştirilmiş bir OSError ile başarısız olur (send2trash mac
# backend hatayı localizedFailureReason() ile fırlatır). Tespiti hata METNİNE
# değil KONUMA dayandırıyoruz — metin dile göre değişir, konum değişmez.
FULL_DISK_ACCESS_CATEGORIES = frozenset(
    {ResidueCategory.CONTAINERS, ResidueCategory.GROUP_CONTAINERS}
)


def build_trash_banner(
    succeeded_count: int,
    freed: str,
    failed_items: list[OrphanItem],
) -> str:
    """Çöp'e taşıma sonucu için kullanıcıya gösterilecek özet metnini üretir.

    Saf fonksiyon (GUI'siz, test edilebilir). Başarısızlıklar arasında TCC ile
    korunan bir konum (Containers / Group Containers) varsa, genel bir "izin
    hatası" yerine kullanıcıya Tam Disk Erişimi için eyleme geçirilebilir
    yönlendirme gösterir.
    """
    lines = [
        f"✓ {succeeded_count} öğe Çöp Kutusu'na taşındı · {freed} boşaltıldı."
    ]
    if failed_items:
        needs_full_disk_access = any(
            item.category in FULL_DISK_ACCESS_CATEGORIES for item in failed_items
        )
        if needs_full_disk_access:
            lines.append(
                f"⚠ {len(failed_items)} öğe taşınamadı. Bu öğeler için macOS'un "
                "Tam Disk Erişimi izni gerekiyor: Sistem Ayarları → Gizlilik ve "
                "Güvenlik → Tam Disk Erişimi → maClean'e izin verin, sonra "
                "uygulamayı yeniden başlatıp tekrar deneyin."
            )
        else:
            lines.append(
                f"⚠ {len(failed_items)} öğe taşınamadı (izin veya erişim hatası)."
            )
    return "\n".join(lines)
