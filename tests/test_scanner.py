"""scanner.py için birim testleri."""

from maclean import scanner
from maclean.models import MatchConfidence, ResidueCategory


def test_discovers_installed_bundle_ids(tmp_path, app_bundle_factory):
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Spotify.app", "com.spotify.client", "Spotify")
    app_bundle_factory(apps, "Notion.app", "notion.id", "Notion")

    ids, names = scanner.discover_installed_apps([apps])

    assert "com.spotify.client" in ids
    assert "notion.id" in ids
    assert names["com.spotify.client"] == "Spotify"


def test_bundle_ids_are_lowercased(tmp_path, app_bundle_factory):
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Foo.app", "COM.Example.Foo", "Foo")

    ids, _ = scanner.discover_installed_apps([apps])

    assert "com.example.foo" in ids


def test_finds_apps_in_nested_vendor_folder(tmp_path, app_bundle_factory):
    """Vendor'ın .app'i bir alt klasöre gömmesi doğru bulunmalı."""
    apps = tmp_path / "Applications"
    app_bundle_factory(
        apps, "Native Instruments/Native Access.app",
        "com.native-instruments.access", "Native Access",
    )

    ids, _ = scanner.discover_installed_apps([apps])

    assert "com.native-instruments.access" in ids


def test_helper_bundle_inside_app_is_not_counted(tmp_path, app_bundle_factory):
    """Senaryo 7: bir .app İÇİNDEKİ yardımcı .app ayrı uygulama sayılmaz."""
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Big.app", "com.big.app", "Big")
    app_bundle_factory(
        apps, "Big.app/Contents/Frameworks/Helper.app",
        "com.big.helper", "Helper",
    )

    ids, _ = scanner.discover_installed_apps([apps])

    assert "com.big.app" in ids
    assert "com.big.helper" not in ids  # budama çalışmalı


def test_skips_bundle_without_identifier(tmp_path, app_bundle_factory):
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Broken.app", bundle_id=None, name="Broken")
    app_bundle_factory(apps, "Good.app", "com.good.app", "Good")

    ids, names = scanner.discover_installed_apps([apps])

    assert "com.good.app" in ids
    assert names == {"com.good.app": "Good"}  # kimliksiz bundle atlandı


def test_nonexistent_root_is_ignored(tmp_path):
    missing = tmp_path / "does-not-exist"
    ids, names = scanner.discover_installed_apps([missing])
    assert ids == set()
    assert names == {}


# ==========================================================================
# find_orphans — plandaki 7 kritik senaryo + ek güvenlik testleri
# ==========================================================================

def _orphan_names(orphans):
    return {o.path.name for o in orphans}


def test_s1_unlisted_bundle_id_folder_is_orphan(tmp_path, residue_factory):
    """Senaryo 1: yüklü olmayan bundle-id'li klasör öksüz tespit edilir."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.deletedapp")

    orphans = scanner.find_orphans(set(), set(), library_root=lib)

    assert "com.example.deletedapp" in _orphan_names(orphans)
    item = next(o for o in orphans if o.path.name == "com.example.deletedapp")
    assert item.confidence is MatchConfidence.BUNDLE_ID
    assert item.bundle_id == "com.example.deletedapp"
    assert item.category is ResidueCategory.CACHE


def test_s2_installed_app_residue_never_orphaned(tmp_path, residue_factory):
    """Senaryo 2 (KRİTİK): yüklü uygulamanın kalıntısı ASLA öksüz sayılmaz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.realapp")

    orphans = scanner.find_orphans(
        {"com.example.realapp"}, {"RealApp"}, library_root=lib,
    )

    assert orphans == []


def test_s3_apple_prefixed_never_orphaned(tmp_path, residue_factory):
    """Senaryo 3 (KRİTİK): com.apple.* önekli hiçbir şey öksüz sayılmaz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Preferences", "com.apple.unknownthing.plist", is_dir=False)

    orphans = scanner.find_orphans(set(), set(), library_root=lib)

    assert orphans == []


def test_s4_name_based_matches_installed_not_orphan(tmp_path, residue_factory):
    """Senaryo 4: yüklü uygulamayla fuzzy eşleşen isim bazlı klasör öksüz değil."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Sublime Text")

    orphans = scanner.find_orphans(set(), {"Sublime Text"}, library_root=lib)

    assert orphans == []


def test_s5_name_based_no_match_is_orphan(tmp_path, residue_factory):
    """Senaryo 5: hiçbir yüklü uygulamayla eşleşmeyen isim bazlı klasör öksüz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Some Old Tool")

    orphans = scanner.find_orphans(set(), {"Spotify", "Notion"}, library_root=lib)

    item = next(o for o in orphans if o.path.name == "Some Old Tool")
    assert item.confidence is MatchConfidence.NAME_FUZZY
    assert item.bundle_id is None


def test_s6_vendor_umbrella_only_flags_deleted_subproduct(tmp_path, residue_factory):
    """Senaryo 6: şemsiye klasörün kendisi aday olmaz; sadece silinmiş alt ürün."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Adobe/Photoshop")    # yüklü
    residue_factory(lib, "Application Support", "Adobe/OldProduct")   # silinmiş

    orphans = scanner.find_orphans(
        set(), {"Adobe Photoshop"}, library_root=lib,
    )

    names = _orphan_names(orphans)
    assert "Adobe" not in names        # şemsiye klasör asla işaretlenmez
    assert "Photoshop" not in names    # "Adobe Photoshop" yüklü → eşleşti
    assert "OldProduct" in names       # silinmiş alt ürün öksüz


def test_s7_helper_bundle_pruning(tmp_path, app_bundle_factory):
    """Senaryo 7: .app İÇİNDEKİ yardımcı .app ayrı yüklü uygulama sayılmaz."""
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Big.app", "com.big.app", "Big")
    app_bundle_factory(
        apps, "Big.app/Contents/Frameworks/Helper.app", "com.big.helper", "Helper",
    )

    ids, _ = scanner.discover_installed_apps([apps])

    assert "com.big.app" in ids
    assert "com.big.helper" not in ids


# --- Ek güvenlik / doğruluk testleri ---

def test_group_container_teamid_prefixed_installed_not_orphan(tmp_path, residue_factory):
    """Takım-kimliği önekli group container, alttaki uygulama yüklüyse öksüz değil."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Group Containers", "ABCDE12345.com.example.realapp")

    orphans = scanner.find_orphans(
        {"com.example.realapp"}, set(), library_root=lib,
    )

    assert orphans == []


def test_helper_subnamespace_of_installed_app_not_orphan(tmp_path, residue_factory):
    """Yüklü uygulamanın alt-namespace'i (helper/updater) öksüz sayılmaz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.foo.bar.ShipIt")       # Squirrel updater
    residue_factory(lib, "Application Support", "com.foo.bar.helper")

    orphans = scanner.find_orphans({"com.foo.bar"}, {"Foo Bar"}, library_root=lib)

    assert orphans == []


def test_sibling_bundle_id_still_orphaned(tmp_path, residue_factory):
    """Kardeş kimlik (alt-namespace değil) hâlâ öksüz tespit edilebilmeli."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.foo.baz")  # com.foo.bar'ın alt-namespace'i DEĞİL

    orphans = scanner.find_orphans({"com.foo.bar"}, {"Foo Bar"}, library_root=lib)

    assert "com.foo.baz" in _orphan_names(orphans)


def test_group_prefixed_orphan_detected(tmp_path, residue_factory):
    """'group.' önekli, karşılığı olmayan container öksüz tespit edilir."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Group Containers", "group.com.example.deletedapp")

    orphans = scanner.find_orphans(set(), set(), library_root=lib)

    item = next(
        o for o in orphans if o.path.name == "group.com.example.deletedapp"
    )
    assert item.bundle_id == "com.example.deletedapp"


def test_cautious_location_non_bundle_name_skipped(tmp_path, residue_factory):
    """Temkinli konumda bundle-id deseninde olmayan ad atlanır (fuzzy fallback yok)."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Scripts", "Some Random Folder")

    orphans = scanner.find_orphans(set(), set(), library_root=lib)

    assert orphans == []


def test_preferences_plist_orphan_prettifies_name(tmp_path, residue_factory):
    """Preferences .plist öksüzü: bundle-id soyulur, ad okunabilir hale getirilir."""
    lib = tmp_path / "Library"
    residue_factory(
        lib, "Preferences", "com.adobe.PhotoshopElements.plist", is_dir=False,
    )

    orphans = scanner.find_orphans(set(), set(), library_root=lib)

    item = next(o for o in orphans if "PhotoshopElements" in o.path.name)
    assert item.bundle_id == "com.adobe.photoshopelements"
    assert item.display_name == "Photoshop Elements"
    assert item.category is ResidueCategory.PREFERENCES


def test_orphan_reports_directory_size(tmp_path, residue_factory):
    """Dizin boyutu özyinelemeli hesaplanır."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.deletedapp", size=4096)

    orphans = scanner.find_orphans(set(), set(), library_root=lib)

    item = next(o for o in orphans if o.path.name == "com.example.deletedapp")
    assert item.size_bytes >= 4096


def test_symlink_escaping_library_is_skipped(tmp_path, residue_factory):
    """Savunma katmanı: ~/Library dışına işaret eden sembolik link elenir."""
    lib = tmp_path / "Library"
    outside = tmp_path / "outside_secret"
    outside.mkdir(parents=True)
    caches = lib / "Caches"
    caches.mkdir(parents=True)
    # Bundle-id desenli bir adla dışarıya link kur.
    (caches / "com.example.evil").symlink_to(outside, target_is_directory=True)

    orphans = scanner.find_orphans(set(), set(), library_root=lib)

    assert "com.example.evil" not in _orphan_names(orphans)
