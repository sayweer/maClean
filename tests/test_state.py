from datetime import datetime

from maclean.models import ApplicationRecord, EvidenceLevel
from maclean.state import StateStore


def _app(tmp_path):
    return ApplicationRecord(
        bundle_id="com.example.foo",
        name="Foo",
        path=tmp_path / "Foo.app",
        helper_bundle_ids=("com.example.foo.helper",),
    )


def test_inventory_is_written_and_missing_app_is_observed(tmp_path):
    store = StateStore(tmp_path / "state.json")
    app = _app(tmp_path)

    store.update_inventory([app])

    assert (
        store.evidence_for(app.bundle_id, set())
        is EvidenceLevel.OBSERVED_MISSING
    )


def test_explicit_removal_has_highest_evidence(tmp_path):
    store = StateStore(tmp_path / "state.json")
    app = _app(tmp_path)
    store.update_inventory([app])

    store.record_explicit_removal(app)

    assert (
        store.evidence_for(app.bundle_id, set())
        is EvidenceLevel.EXPLICIT_REMOVAL
    )


def test_corrupt_state_falls_back_safely(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")

    assert StateStore(path).load()["schema_version"] == 1


def test_complete_removal_is_not_partial(tmp_path):
    store = StateStore(tmp_path / "state.json")
    app = _app(tmp_path)

    store.record_explicit_removal(app)

    record = store.load()["explicit_removals"][app.bundle_id]
    assert record["partial"] is False


def test_partial_removal_is_flagged(tmp_path):
    store = StateStore(tmp_path / "state.json")
    app = _app(tmp_path)

    store.record_explicit_removal(
        app, ((tmp_path / "Caches" / "leftover", "izin reddedildi"),)
    )

    record = store.load()["explicit_removals"][app.bundle_id]
    assert record["partial"] is True
    assert record["failed_paths"][0]["error"] == "izin reddedildi"


def test_old_record_without_partial_still_has_highest_evidence(tmp_path):
    """Geriye uyumluluk: 'partial' alanı olmayan eski kayıt sorunsuz okunur."""
    path = tmp_path / "state.json"
    store = StateStore(path)
    app = _app(tmp_path)
    store.update_inventory([app])
    data = store.load()
    data["explicit_removals"][app.bundle_id] = {
        "name": app.name,
        "path": str(app.path),
        "removed_at": "2026-01-01T00:00:00",
        "helper_bundle_ids": [],
        "failed_paths": [],
    }  # 'partial' alanı yok (eski şema)
    store.save(data)

    assert (
        store.evidence_for(app.bundle_id, set())
        is EvidenceLevel.EXPLICIT_REMOVAL
    )
