import plistlib
from pathlib import Path

import pytest

from maclean.applications import (
    ApplicationError,
    read_application,
    validate_removable_application,
)
from maclean.models import ApplicationRecord


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
