"""models.py ve constants.py için temel birim testleri (Faz 1 doğrulaması)."""

from datetime import datetime
from pathlib import Path

from maclean import constants
from maclean.models import (
    MatchConfidence,
    OrphanItem,
    ResidueCategory,
    human_readable_size,
)


def test_orphan_item_defaults_to_unselected():
    """Güvenlik gereği: yeni bir OrphanItem varsayılan olarak seçili DEĞİLdir."""
    item = OrphanItem(
        display_name="Deleted App",
        bundle_id="com.example.deletedapp",
        category=ResidueCategory.CACHE,
        path=Path("/tmp/whatever"),
        size_bytes=1024,
        last_modified=datetime(2024, 1, 1),
        confidence=MatchConfidence.BUNDLE_ID,
    )
    assert item.selected is False


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
