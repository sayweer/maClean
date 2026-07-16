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
