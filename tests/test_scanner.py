"""scanner.scan_orphans için birim testleri.

Testler doğrudan üretim yolunu (`scan_orphans`) çağırır; böylece kanıt
seviyesi, seçilebilirlik ve reason mantığı da kapsanır. Kurulu uygulama
keşfi (`applications.discover_applications`) test_applications.py altındadır.
"""

from datetime import datetime, timedelta

from maclean.scanner import scan_orphans
from maclean.models import EvidenceLevel, ResidueCategory
from maclean.state import StateStore


def _scan(installed_ids, installed_names, library_root, now=None):
    return scan_orphans(
        installed_ids,
        installed_names,
        library_root=library_root,
        now=now,
    ).items


def _orphan_names(orphans):
    return {o.path.name for o in orphans}


# ==========================================================================
# Plandaki 7 kritik senaryo + ek güvenlik testleri
# ==========================================================================

def test_s1_unlisted_bundle_id_folder_is_orphan(tmp_path, residue_factory):
    """Senaryo 1: yüklü olmayan bundle-id'li klasör öksüz tespit edilir."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.deletedapp")

    orphans = _scan(set(), set(), lib)

    assert "com.example.deletedapp" in _orphan_names(orphans)
    item = next(o for o in orphans if o.path.name == "com.example.deletedapp")
    assert item.evidence is EvidenceLevel.EXACT_IDENTIFIER
    assert item.bundle_id == "com.example.deletedapp"
    assert item.category is ResidueCategory.CACHE


def test_s2_installed_app_residue_never_orphaned(tmp_path, residue_factory):
    """Senaryo 2 (KRİTİK): yüklü uygulamanın kalıntısı ASLA öksüz sayılmaz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.realapp")

    orphans = _scan({"com.example.realapp"}, {"RealApp"}, lib)

    assert orphans == ()


def test_s3_apple_prefixed_never_orphaned(tmp_path, residue_factory):
    """Senaryo 3 (KRİTİK): com.apple.* önekli hiçbir şey öksüz sayılmaz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Preferences", "com.apple.unknownthing.plist", is_dir=False)

    orphans = _scan(set(), set(), lib)

    assert orphans == ()


def test_team_prefixed_apple_data_is_never_orphaned(tmp_path, residue_factory):
    lib = tmp_path / "Library"
    residue_factory(
        lib,
        "Preferences",
        "TEAM123.systemgroup.com.apple.shared.plist",
        is_dir=False,
    )

    orphans = _scan(set(), set(), lib)

    assert orphans == ()


def test_third_party_id_embedding_apple_still_visible(tmp_path, residue_factory):
    """Apple koruması yalnızca gerçek önekle çalışır; ortada geçen 'com.apple'
    3. parti kimliği gizlememelidir (1.3 regresyon)."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "org.thirdparty.com.apple.helper")

    orphans = _scan(set(), set(), lib)

    assert "org.thirdparty.com.apple.helper" in _orphan_names(orphans)


def test_s4_name_based_matches_installed_not_orphan(tmp_path, residue_factory):
    """Senaryo 4: yüklü uygulamayla fuzzy eşleşen isim bazlı klasör öksüz değil."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Sublime Text")

    orphans = _scan(set(), {"Sublime Text"}, lib)

    assert orphans == ()


def test_s5_name_based_no_match_is_orphan(tmp_path, residue_factory):
    """Senaryo 5: hiçbir yüklü uygulamayla eşleşmeyen isim bazlı klasör öksüz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Some Old Tool")

    orphans = _scan(set(), {"Spotify", "Notion"}, lib)

    item = next(o for o in orphans if o.path.name == "Some Old Tool")
    assert item.evidence is EvidenceLevel.NAME_ONLY
    assert item.bundle_id is None
    assert item.selectable is False  # 1.1: NAME_ONLY salt-inceleme


def test_name_only_orphan_is_review_only(tmp_path, residue_factory):
    """1.1 regresyon: son 30 gün kısıtı kaldırılsa (now ileri alınsa) bile
    NAME_ONLY aday seçilemez kalır — tek sebep sahipliğin doğrulanamamasıdır."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Some Old Tool", size=4096)
    future = datetime.now() + timedelta(days=60)

    item = next(
        o for o in _scan(set(), {"Spotify"}, lib, now=future)
        if o.path.name == "Some Old Tool"
    )

    assert item.evidence is EvidenceLevel.NAME_ONLY
    assert item.selectable is False
    assert "inceleme" in item.reason


def test_exact_identifier_orphan_is_selectable(tmp_path, residue_factory):
    """Pozitif kontrol: kimliği doğrulanmış, eski ve boyutu okunabilen öksüz
    seçilebilir olur (selectable koşulunun gerçekten iş yaptığını doğrular)."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.deletedapp", size=4096)
    future = datetime.now() + timedelta(days=60)

    item = next(
        o for o in _scan(set(), set(), lib, now=future)
        if o.path.name == "com.example.deletedapp"
    )

    assert item.evidence is EvidenceLevel.EXACT_IDENTIFIER
    assert item.selectable is True


def test_s6_vendor_umbrella_only_flags_deleted_subproduct(tmp_path, residue_factory):
    """Senaryo 6: şemsiye klasörün kendisi aday olmaz; sadece silinmiş alt ürün."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Adobe/Photoshop")    # yüklü
    residue_factory(lib, "Application Support", "Adobe/OldProduct")   # silinmiş

    orphans = _scan(set(), {"Adobe Photoshop"}, lib)

    names = _orphan_names(orphans)
    assert "Adobe" not in names        # şemsiye klasör asla işaretlenmez
    assert "Photoshop" not in names    # "Adobe Photoshop" yüklü → eşleşti
    assert "OldProduct" in names       # silinmiş alt ürün öksüz


# --- Ek güvenlik / doğruluk testleri ---

def test_group_container_teamid_prefixed_installed_not_orphan(tmp_path, residue_factory):
    """Takım-kimliği önekli group container, alttaki uygulama yüklüyse öksüz değil."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Group Containers", "ABCDE12345.com.example.realapp")

    orphans = _scan({"com.example.realapp"}, set(), lib)

    assert orphans == ()


def test_helper_subnamespace_of_installed_app_not_orphan(tmp_path, residue_factory):
    """Yüklü uygulamanın alt-namespace'i (helper/updater) öksüz sayılmaz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.foo.bar.ShipIt")       # Squirrel updater
    residue_factory(lib, "Application Support", "com.foo.bar.helper")

    orphans = _scan({"com.foo.bar"}, {"Foo Bar"}, lib)

    assert orphans == ()


def test_sibling_bundle_id_still_orphaned(tmp_path, residue_factory):
    """Kardeş kimlik (alt-namespace değil) hâlâ öksüz tespit edilebilmeli."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.foo.baz")  # com.foo.bar'ın alt-namespace'i DEĞİL

    orphans = _scan({"com.foo.bar"}, {"Foo Bar"}, lib)

    assert "com.foo.baz" in _orphan_names(orphans)


def test_group_containers_are_excluded_from_legacy_scan(tmp_path, residue_factory):
    """Paylaşılan Group Containers eski heuristik taramada hiç önerilmez."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Group Containers", "group.com.example.deletedapp")

    orphans = _scan(set(), set(), lib)

    assert orphans == ()


def test_cautious_location_non_bundle_name_skipped(tmp_path, residue_factory):
    """Temkinli konumda bundle-id deseninde olmayan ad atlanır (fuzzy fallback yok)."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Scripts", "Some Random Folder")

    orphans = _scan(set(), set(), lib)

    assert orphans == ()


def test_application_scripts_are_excluded_from_legacy_scan(
    tmp_path, residue_factory
):
    lib = tmp_path / "Library"
    residue_factory(
        lib, "Application Scripts", "com.example.deletedapp",
    )

    assert _scan(set(), set(), lib) == ()


def test_preferences_plist_orphan_prettifies_name(tmp_path, residue_factory):
    """Preferences .plist öksüzü: bundle-id soyulur, ad okunabilir hale getirilir."""
    lib = tmp_path / "Library"
    residue_factory(
        lib, "Preferences", "com.adobe.PhotoshopElements.plist", is_dir=False,
    )

    orphans = _scan(set(), set(), lib)

    item = next(o for o in orphans if "PhotoshopElements" in o.path.name)
    assert item.bundle_id == "com.adobe.photoshopelements"
    assert item.display_name == "Photoshop Elements"
    assert item.category is ResidueCategory.PREFERENCES


def test_orphan_reports_directory_size(tmp_path, residue_factory):
    """Dizin boyutu özyinelemeli hesaplanır."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.deletedapp", size=4096)

    orphans = _scan(set(), set(), lib)

    item = next(o for o in orphans if o.path.name == "com.example.deletedapp")
    assert item.size_bytes >= 4096


def test_known_tool_cache_never_flagged(tmp_path, residue_factory):
    """Denylist: pip/Homebrew gibi araç önbellekleri asla öksüz önerilmez."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "pip")
    residue_factory(lib, "Caches", "Homebrew")
    residue_factory(lib, "Caches", "ms-playwright-go")

    orphans = _scan(set(), set(), lib)

    assert orphans == ()


def test_version_numbered_name_not_treated_as_bundle_id(tmp_path, residue_factory):
    """Sürüm numaralı klasör adı (AndroidStudio2024.3.2) bundle-id sanılmaz.

    Google şemsiyesi altında olduğundan isim bazlı değerlendirilir; anlamlı
    bir görünen ad alır ve NAME_ONLY olarak işaretlenir — asla '2' gibi
    anlamsız bir bundle-id adı almaz.
    """
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "Google/AndroidStudio2024.3.2")

    orphans = _scan(set(), {"Android Studio"}, lib)

    item = next(o for o in orphans if o.path.name == "AndroidStudio2024.3.2")
    assert item.evidence is EvidenceLevel.NAME_ONLY
    assert item.bundle_id is None
    assert "AndroidStudio2024.3.2" in item.display_name  # anlamlı ad, "2" değil


def test_bundle_id_looking_app_name_of_installed_app_not_orphan(
    tmp_path, residue_factory
):
    """Bundle-id GÖRÜNÜMLÜ ad (zoom.us) yüklü uygulama adıyla eşleşiyorsa öksüz değil.

    Zoom'un veri klasörü 'zoom.us' desene uyar ama gerçek kimliği us.zoom.xos'tur;
    fuzzy veto olmadan yüksek güvenle yanlış işaretlenirdi.
    """
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "zoom.us")

    orphans = _scan({"us.zoom.xos"}, {"zoom.us"}, lib)

    assert orphans == ()


def test_bundle_id_looking_name_without_matching_app_still_orphan(
    tmp_path, residue_factory
):
    """Zoom silinmişse aynı 'zoom.us' klasörü yine öksüz tespit edilmeli."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "zoom.us")

    orphans = _scan(set(), {"Spotify"}, lib)

    assert "zoom.us" in _orphan_names(orphans)


def test_known_alias_folder_of_installed_app_not_orphan(tmp_path, residue_factory):
    """Alias: VS Code yüklüyken 'Code' klasörü öksüz sayılmaz."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Code")

    orphans = _scan({"com.microsoft.vscode"}, {"Visual Studio Code"}, lib)

    assert orphans == ()


def test_known_alias_folder_without_app_still_orphan(tmp_path, residue_factory):
    """Alias yalnızca uygulama yüklüyken korur; VS Code silinmişse 'Code' öksüzdür."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "Code")

    orphans = _scan(set(), {"Spotify"}, lib)

    item = next(o for o in orphans if o.path.name == "Code")
    assert item.evidence is EvidenceLevel.NAME_ONLY


def test_non_latin_name_is_review_only(tmp_path, residue_factory):
    """Unicode ad korunur; yalnız kanıtsız ve seçimsiz inceleme adayıdır."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Application Support", "카카오톡")

    orphans = _scan(set(), {"Spotify"}, lib)

    assert len(orphans) == 1
    assert orphans[0].display_name == "카카오톡"
    assert orphans[0].evidence is EvidenceLevel.NAME_ONLY
    assert orphans[0].selectable is False


def test_scan_loads_state_once(tmp_path, residue_factory):
    """3.1: kanıt seviyesi snapshot'tan okunur; state aday sayısından bağımsız
    olarak tarama başına yalnızca bir kez yüklenir."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.one")
    residue_factory(lib, "Caches", "com.example.two")
    residue_factory(lib, "Application Support", "com.example.three")

    class CountingStore(StateStore):
        loads = 0

        def load(self):
            type(self).loads += 1
            return super().load()

    store = CountingStore(tmp_path / "state.json")
    scan_orphans(set(), set(), library_root=lib, state_store=store)

    assert CountingStore.loads == 1


def test_scan_aborts_when_requested(tmp_path, residue_factory):
    """3.3: should_abort True dönerse tarama erken biter, aday üretmez."""
    lib = tmp_path / "Library"
    residue_factory(lib, "Caches", "com.example.one")

    report = scan_orphans(set(), set(), library_root=lib, should_abort=lambda: True)

    assert report.items == ()


def test_symlink_escaping_library_is_skipped(tmp_path, residue_factory):
    """Savunma katmanı: ~/Library dışına işaret eden sembolik link elenir."""
    lib = tmp_path / "Library"
    outside = tmp_path / "outside_secret"
    outside.mkdir(parents=True)
    caches = lib / "Caches"
    caches.mkdir(parents=True)
    # Bundle-id desenli bir adla dışarıya link kur.
    (caches / "com.example.evil").symlink_to(outside, target_is_directory=True)

    orphans = _scan(set(), set(), lib)

    assert "com.example.evil" not in _orphan_names(orphans)
