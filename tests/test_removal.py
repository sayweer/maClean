from dataclasses import replace
from pathlib import Path

from maclean import removal
from maclean.applications import read_application
from maclean.models import (
    ApplicationRecord,
    EvidenceLevel,
    RemovalMode,
    ResidueCategory,
)
from maclean.state import StateStore


def _setup_app_and_library(tmp_path, app_bundle_factory, residue_factory):
    apps = tmp_path / "Applications"
    app_path = app_bundle_factory(
        apps, "Foo.app", "com.example.foo", "Foo",
    )
    library = tmp_path / "Library"
    residue_factory(library, "Caches", "com.example.foo", size=100)
    residue_factory(library, "Logs", "com.example.foo", size=200)
    residue_factory(library, "Preferences", "com.example.foo.plist", is_dir=False)
    residue_factory(library, "Application Support", "com.example.foo", size=300)
    residue_factory(library, "Application Support", "Foo", size=400)
    return read_application(app_path), library


def test_standard_and_full_modes_have_safe_defaults(
    tmp_path, app_bundle_factory, residue_factory
):
    app, library = _setup_app_and_library(
        tmp_path, app_bundle_factory, residue_factory,
    )

    standard = removal.build_removal_plan(
        app, RemovalMode.STANDARD, [app], library_root=library,
    )
    full = removal.build_removal_plan(
        app, RemovalMode.FULL, [app], library_root=library,
    )

    standard_selected = {
        item.category for item in standard.items if item.selected_by_default
    }
    full_selected = {
        item.category for item in full.items if item.selected_by_default
    }
    assert standard_selected == {ResidueCategory.CACHE, ResidueCategory.LOGS}
    assert ResidueCategory.PREFERENCES in full_selected
    assert ResidueCategory.APPLICATION_SUPPORT in full_selected
    name_only = next(item for item in full.items if item.path.name == "Foo")
    assert name_only.evidence is EvidenceLevel.NAME_ONLY
    assert name_only.selected_by_default is False


def test_shared_group_is_protected_when_another_app_owns_it(
    tmp_path, app_bundle_factory, residue_factory
):
    app_path = app_bundle_factory(
        tmp_path / "Applications", "Foo.app", "com.example.foo", "Foo",
    )
    base = read_application(app_path)
    app = replace(base, application_groups=("group.com.example.shared",))
    other = ApplicationRecord(
        bundle_id="com.example.other",
        name="Other",
        path=tmp_path / "Other.app",
        application_groups=("group.com.example.shared",),
    )
    library = tmp_path / "Library"
    residue_factory(
        library, "Group Containers", "group.com.example.shared", size=50,
    )

    plan = removal.build_removal_plan(
        app, RemovalMode.FULL, [app, other], library_root=library,
    )

    item = next(item for item in plan.items if item.category is ResidueCategory.GROUP_CONTAINERS)
    assert item.selectable is False
    assert item.evidence is EvidenceLevel.SHARED_OR_UNKNOWN


def test_exclusive_group_is_selected_only_in_full_mode(
    tmp_path, app_bundle_factory, residue_factory
):
    app_path = app_bundle_factory(
        tmp_path / "Applications", "Foo.app", "com.example.foo", "Foo",
    )
    base = read_application(app_path)
    app = replace(base, application_groups=("group.com.example.foo",))
    library = tmp_path / "Library"
    residue_factory(
        library, "Group Containers", "group.com.example.foo", size=50,
    )

    standard = removal.build_removal_plan(
        app, RemovalMode.STANDARD, [app], library_root=library,
    )
    full = removal.build_removal_plan(
        app, RemovalMode.FULL, [app], library_root=library,
    )

    standard_item = next(
        item for item in standard.items
        if item.category is ResidueCategory.GROUP_CONTAINERS
    )
    full_item = next(
        item for item in full.items
        if item.category is ResidueCategory.GROUP_CONTAINERS
    )
    assert standard_item.selected_by_default is False
    assert standard_item.selectable is False
    assert full_item.selected_by_default is True
    assert full_item.selectable is True


def test_application_failure_prevents_residue_moves(
    tmp_path, app_bundle_factory, residue_factory, monkeypatch
):
    app, library = _setup_app_and_library(
        tmp_path, app_bundle_factory, residue_factory,
    )
    plan = removal.build_removal_plan(
        app, RemovalMode.FULL, [app], library_root=library,
    )
    calls = []

    def fail_app(paths):
        calls.append(paths)
        return [], [(paths[0], "izin reddedildi")]

    monkeypatch.setattr(removal, "is_application_running", lambda _app: False)
    monkeypatch.setattr(removal.trash, "move_to_trash", fail_app)

    result = removal.execute_removal(
        plan,
        state_store=StateStore(tmp_path / "state.json"),
    )

    assert result.application_moved is False
    assert len(calls) == 1
    assert calls[0] == [app.path]


def test_running_application_aborts_before_any_move(
    tmp_path, app_bundle_factory, residue_factory, monkeypatch
):
    app, library = _setup_app_and_library(
        tmp_path, app_bundle_factory, residue_factory,
    )
    plan = removal.build_removal_plan(
        app, RemovalMode.STANDARD, [app], library_root=library,
    )
    monkeypatch.setattr(removal, "is_application_running", lambda _app: True)
    monkeypatch.setattr(
        removal.trash,
        "move_to_trash",
        lambda _paths: (_ for _ in ()).throw(AssertionError("çağrılmamalı")),
    )

    result = removal.execute_removal(
        plan,
        state_store=StateStore(tmp_path / "state.json"),
    )

    assert result.application_moved is False
    assert "çalışıyor" in result.aborted_reason


def test_plan_skips_unnecessary_system_entitlement_scans(
    tmp_path, app_bundle_factory, monkeypatch
):
    app_path = app_bundle_factory(
        tmp_path / "Applications", "Foo.app", "com.example.foo", "Foo",
    )
    app = read_application(app_path)
    protectors = [
        ApplicationRecord(
            bundle_id=f"com.apple.system{index}",
            name=f"System {index}",
            path=Path(f"/System/Applications/System{index}.app"),
            selectable=False,
        )
        for index in range(100)
    ]
    calls = []

    def enrich(record):
        calls.append(record.bundle_id)
        return record

    monkeypatch.setattr(removal, "enrich_application_groups", enrich)

    removal.build_removal_plan(
        app,
        RemovalMode.STANDARD,
        [app, *protectors],
        library_root=tmp_path / "Library",
    )

    assert calls == [app.bundle_id]


def test_application_is_moved_before_residues(
    tmp_path, app_bundle_factory, residue_factory, monkeypatch
):
    app, library = _setup_app_and_library(
        tmp_path, app_bundle_factory, residue_factory,
    )
    plan = removal.build_removal_plan(
        app, RemovalMode.STANDARD, [app], library_root=library,
    )
    calls = []

    def succeed(paths):
        calls.append(paths[0])
        return list(paths), []

    monkeypatch.setattr(removal, "is_application_running", lambda _app: False)
    monkeypatch.setattr(removal.trash, "move_to_trash", succeed)

    result = removal.execute_removal(
        plan,
        state_store=StateStore(tmp_path / "state.json"),
    )

    assert result.application_moved is True
    assert calls[0] == app.path
    assert set(calls[1:]) == set(plan.default_selected_paths)


def test_stale_application_plan_is_aborted(
    tmp_path, app_bundle_factory, residue_factory, monkeypatch
):
    app, library = _setup_app_and_library(
        tmp_path, app_bundle_factory, residue_factory,
    )
    plan = removal.build_removal_plan(
        app, RemovalMode.STANDARD, [app], library_root=library,
    )
    (app.path / "changed").write_text("changed", encoding="utf-8")
    app.path.touch()
    monkeypatch.setattr(removal, "is_application_running", lambda _app: False)

    result = removal.execute_removal(
        plan,
        state_store=StateStore(tmp_path / "state.json"),
    )

    assert result.application_moved is False
    assert "değişti" in result.aborted_reason
