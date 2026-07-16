"""models.py ve constants.py için temel birim testleri (Faz 1 doğrulaması)."""

from datetime import datetime
from pathlib import Path

from maclean import constants
from maclean.models import (
    FULL_DISK_ACCESS_CATEGORIES,
    MatchConfidence,
    OrphanItem,
    ResidueCategory,
    build_trash_banner,
    human_readable_size,
)


def test_orphan_item_selection_is_not_domain_state():
    """Seçim GUI/controller durumudur; alan modelinde tutulmaz."""
    item = OrphanItem(
        display_name="Deleted App",
        bundle_id="com.example.deletedapp",
        category=ResidueCategory.CACHE,
        path=Path("/tmp/whatever"),
        size_bytes=1024,
        last_modified=datetime(2024, 1, 1),
        confidence=MatchConfidence.BUNDLE_ID,
    )
    assert not hasattr(item, "selected")
    assert item.selectable is False


def test_scan_locations_cover_every_category():
    """Her ResidueCategory'nin bir tarama konumu olmalı (eksik kalmasın)."""
    assert set(constants.SCAN_LOCATIONS) == set(ResidueCategory)


def test_fuzzy_and_cautious_location_sets_are_disjoint():
    """Bir konum aynı anda hem fuzzy hem de temkinli olamaz."""
    assert not (constants.NAME_FUZZY_LOCATIONS & constants.CAUTIOUS_LOCATIONS)


def test_bundle_id_pattern_matches_real_ids():
    assert constants.BUNDLE_ID_PATTERN.match("com.adobe.Photoshop")
    assert constants.BUNDLE_ID_PATTERN.match("org.mozilla.firefox")
    # Nokta içermeyen sade adlar bundle-id sayılmaz
    assert not constants.BUNDLE_ID_PATTERN.match("Sublime Text")
    assert not constants.BUNDLE_ID_PATTERN.match("Spotify")


def test_human_readable_size():
    assert human_readable_size(0) == "0 B"
    assert human_readable_size(512) == "512 B"
    assert human_readable_size(1536) == "1.5 KB"
    assert human_readable_size(5 * 1024 * 1024) == "5.0 MB"
    assert human_readable_size(3 * 1024**3) == "3.0 GB"
    assert human_readable_size(None) == "Bilinmiyor"


def _make_item(category: ResidueCategory, name: str = "App") -> OrphanItem:
    """build_trash_banner testleri için minimal bir OrphanItem üretir."""
    return OrphanItem(
        display_name=name,
        bundle_id=None,
        category=category,
        path=Path("/tmp") / name,
        size_bytes=1024,
        last_modified=datetime(2024, 1, 1),
        confidence=MatchConfidence.BUNDLE_ID,
    )


def test_full_disk_access_categories_are_the_tcc_protected_ones():
    """Tam Disk Erişimi gerektiren kategoriler yalnızca (Group) Containers'tır."""
    assert FULL_DISK_ACCESS_CATEGORIES == frozenset(
        {ResidueCategory.CONTAINERS, ResidueCategory.GROUP_CONTAINERS}
    )


def test_banner_success_only():
    """Başarısızlık yoksa yalnızca başarı satırı gösterilir."""
    banner = build_trash_banner(3, "1.5 GB", [])
    assert banner == "✓ 3 öğe Çöp Kutusu'na taşındı · 1.5 GB boşaltıldı."
    assert "taşınamadı" not in banner


def test_banner_tcc_failure_shows_full_disk_access_guidance():
    """Containers gibi TCC konumundaki başarısızlıkta Tam Disk Erişimi yönlendirmesi çıkar."""
    failed = [_make_item(ResidueCategory.CONTAINERS, "UTM")]
    banner = build_trash_banner(0, "0 B", failed)
    assert "Tam Disk Erişimi" in banner
    assert "Gizlilik ve Güvenlik" in banner
    assert "1 öğe taşınamadı" in banner
    assert not banner.startswith("✓")


def test_banner_generic_failure_has_no_fda_guidance():
    """TCC dışı bir konumdaki (Cache) başarısızlık genel mesaj gösterir, FDA yönlendirmesi vermez."""
    failed = [_make_item(ResidueCategory.CACHE, "Photoshop")]
    banner = build_trash_banner(0, "0 B", failed)
    assert "taşınamadı" in banner
    assert "Tam Disk Erişimi" not in banner


def test_banner_mixed_failure_prefers_fda_guidance():
    """Karışık başarısızlıkta (biri TCC), eyleme geçirilebilir FDA yönlendirmesi öncelenir."""
    failed = [
        _make_item(ResidueCategory.CACHE, "Photoshop"),
        _make_item(ResidueCategory.GROUP_CONTAINERS, "Office"),
    ]
    banner = build_trash_banner(1, "50 MB", failed)
    assert "Tam Disk Erişimi" in banner
    assert "2 öğe taşınamadı" in banner
