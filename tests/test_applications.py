import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from maclean import applications
from maclean.applications import (
    ApplicationError,
    discover_applications,
    read_application,
    validate_removable_application,
)
from maclean.models import ApplicationRecord


def _discover(root):
    """Bir kökü tarayıp (bundle_id kümesi, isim eşlemesi, sorunlar) döndürür.

    Koruyucu kökler boş verilir; testler yalnızca seçilebilir kökü değerlendirir.
    """
    apps, issues = discover_applications(
        selectable_roots=(root,), protector_roots=()
    )
    ids = {app.bundle_id for app in apps}
    names = {app.bundle_id: app.name for app in apps}
    return ids, names, issues


# ==========================================================================
# discover_applications — kurulu uygulama keşif senaryoları
# ==========================================================================

def test_discovers_installed_bundle_ids(tmp_path, app_bundle_factory):
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Spotify.app", "com.spotify.client", "Spotify")
    app_bundle_factory(apps, "Notion.app", "notion.id", "Notion")

    ids, names, _ = _discover(apps)

    assert "com.spotify.client" in ids
    assert "notion.id" in ids
    assert names["com.spotify.client"] == "Spotify"


def test_bundle_ids_are_lowercased(tmp_path, app_bundle_factory):
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Foo.app", "COM.Example.Foo", "Foo")

    ids, _, _ = _discover(apps)

    assert "com.example.foo" in ids


def test_finds_apps_in_nested_vendor_folder(tmp_path, app_bundle_factory):
    """Vendor'ın .app'i bir alt klasöre gömmesi doğru bulunmalı."""
    apps = tmp_path / "Applications"
    app_bundle_factory(
        apps, "Native Instruments/Native Access.app",
        "com.native-instruments.access", "Native Access",
    )

    ids, _, _ = _discover(apps)

    assert "com.native-instruments.access" in ids


def test_helper_bundle_inside_app_is_not_counted(tmp_path, app_bundle_factory):
    """Senaryo 7: bir .app İÇİNDEKİ yardımcı .app ayrı uygulama sayılmaz;
    yalnızca ana uygulamanın helper_bundle_ids'ine girer."""
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Big.app", "com.big.app", "Big")
    app_bundle_factory(
        apps, "Big.app/Contents/Frameworks/Helper.app",
        "com.big.helper", "Helper",
    )

    all_apps, _ = discover_applications(
        selectable_roots=(apps,), protector_roots=()
    )
    ids = {app.bundle_id for app in all_apps}

    assert "com.big.app" in ids
    assert "com.big.helper" not in ids  # budama: ayrı kayıt olmamalı
    big = next(app for app in all_apps if app.bundle_id == "com.big.app")
    assert "com.big.helper" in big.helper_bundle_ids


def test_skips_bundle_without_identifier(tmp_path, app_bundle_factory):
    apps = tmp_path / "Applications"
    app_bundle_factory(apps, "Broken.app", bundle_id=None, name="Broken")
    app_bundle_factory(apps, "Good.app", "com.good.app", "Good")

    ids, names, issues = _discover(apps)

    assert "com.good.app" in ids
    assert names == {"com.good.app": "Good"}  # kimliksiz bundle atlandı
    assert any("Broken.app" in str(issue.path) for issue in issues)


def test_nonexistent_root_is_ignored(tmp_path):
    ids, names, _ = _discover(tmp_path / "does-not-exist")
    assert ids == set()
    assert names == {}


def test_read_application_includes_nested_helpers(tmp_path, app_bundle_factory):
    root = tmp_path / "Applications"
    app = app_bundle_factory(root, "Foo.app", "com.example.foo", "Foo")
    app_bundle_factory(
        root,
        "Foo.app/Contents/PlugIns/Share.appex",
        "com.example.foo.share",
        "Share",
    )
    helper = app / "Contents" / "XPCServices" / "Agent.xpc"
    (helper / "Contents").mkdir(parents=True)
    with (helper / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {"CFBundleIdentifier": "com.example.foo.agent", "CFBundleName": "Agent"},
            handle,
        )

    record = read_application(app)

    assert record.bundle_id == "com.example.foo"
    assert record.helper_bundle_ids == (
        "com.example.foo.agent",
        "com.example.foo.share",
    )


def test_symlink_application_is_rejected(tmp_path, app_bundle_factory):
    root = tmp_path / "Applications"
    app = app_bundle_factory(root, "Foo.app", "com.example.foo", "Foo")
    link = root / "Foo Link.app"
    link.symlink_to(app, target_is_directory=True)

    with pytest.raises(ApplicationError, match="Sembolik"):
        read_application(link)


def test_self_bundle_is_not_removable(tmp_path):
    record = ApplicationRecord(
        bundle_id="com.seyit.maclean",
        name="maClean",
        path=tmp_path / "maClean.app",
    )
    assert "kendi kendisini" in validate_removable_application(record)


def test_system_application_is_not_removable():
    record = ApplicationRecord(
        bundle_id="com.example.system",
        name="System",
        path=Path("/System/Applications/System.app"),
    )
    assert "sistem" in validate_removable_application(record)


# ==========================================================================
# is_application_running — argv[0] önek eşleşmesi (1.2)
# ==========================================================================

def _fake_ps(stdout):
    def run(*_args, **_kwargs):
        return SimpleNamespace(stdout=stdout, returncode=0)
    return run


def test_running_app_detected_when_executable_is_argv0(monkeypatch, tmp_path):
    app = ApplicationRecord(
        bundle_id="com.example.foo", name="Foo", path=tmp_path / "Foo.app"
    )
    exe = tmp_path / "Foo.app" / "Contents" / "MacOS" / "Foo"
    monkeypatch.setattr(
        applications.subprocess,
        "run",
        _fake_ps(f"{exe} --background\n/usr/libexec/other\n"),
    )

    assert applications.is_application_running(app) is True


def test_path_only_as_argument_is_not_running(monkeypatch, tmp_path):
    """Yol başka bir sürecin argümanında geçiyorsa çalışıyor sayılmaz
    (eski substring eşleşmesinin yanlış-pozitifi)."""
    app = ApplicationRecord(
        bundle_id="com.example.foo", name="Foo", path=tmp_path / "Foo.app"
    )
    exe = tmp_path / "Foo.app" / "Contents" / "MacOS" / "Foo"
    monkeypatch.setattr(
        applications.subprocess, "run", _fake_ps(f"grep -r {exe} /var/log\n")
    )

    assert applications.is_application_running(app) is False


def test_running_app_with_spaces_in_path_detected(monkeypatch, tmp_path):
    """Yolda boşluk olsa da önek eşleşmesi kaçmaz (eski yanlış-negatif)."""
    app = ApplicationRecord(
        bundle_id="com.example.some", name="Some App", path=tmp_path / "Some App.app"
    )
    exe = tmp_path / "Some App.app" / "Contents" / "MacOS" / "Some App"
    monkeypatch.setattr(
        applications.subprocess, "run", _fake_ps(f"{exe} --flag value\n")
    )

    assert applications.is_application_running(app) is True


def test_ps_failure_blocks_removal_fail_safe(monkeypatch, tmp_path):
    """ps çalıştırılamazsa çalışma durumu doğrulanamaz → güvenli tarafta kal."""
    app = ApplicationRecord(
        bundle_id="com.example.foo", name="Foo", path=tmp_path / "Foo.app"
    )

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="ps", timeout=5)

    monkeypatch.setattr(applications.subprocess, "run", boom)

    assert applications.is_application_running(app) is True
