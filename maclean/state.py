"""Yerel uygulama envanteri ve kaldırma geçmişi."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .models import ApplicationRecord, EvidenceLevel

STATE_VERSION = 1
DEFAULT_STATE_PATH = (
    Path.home() / "Library" / "Application Support" / "maClean" / "state-v1.json"
)


class StateStore:
    def __init__(self, path: Path = DEFAULT_STATE_PATH) -> None:
        self.path = path

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except (OSError, json.JSONDecodeError, TypeError):
            return self._empty()
        if data.get("schema_version") != STATE_VERSION:
            return self._empty()
        data.setdefault("applications", {})
        data.setdefault("explicit_removals", {})
        return data

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, self.path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def update_inventory(self, applications: list[ApplicationRecord]) -> dict:
        data = self.load()
        now = datetime.now().isoformat()
        known = data["applications"]
        for app in applications:
            previous = known.get(app.bundle_id, {})
            known[app.bundle_id] = {
                "name": app.name,
                "path": str(app.path),
                "helper_bundle_ids": list(app.helper_bundle_ids),
                "application_groups": list(app.application_groups),
                "first_seen": previous.get("first_seen", now),
                "last_seen": now,
            }
        self.save(data)
        return data

    def record_explicit_removal(
        self,
        app: ApplicationRecord,
        failed_paths: tuple[tuple[Path, str], ...] = (),
    ) -> None:
        data = self.load()
        data["explicit_removals"][app.bundle_id] = {
            "name": app.name,
            "path": str(app.path),
            "removed_at": datetime.now().isoformat(),
            "helper_bundle_ids": list(app.helper_bundle_ids),
            "failed_paths": [
                {"path": str(path), "error": error} for path, error in failed_paths
            ],
        }
        self.save(data)

    def evidence_for(
        self,
        bundle_id: str,
        current_ids: set[str],
    ) -> EvidenceLevel:
        data = self.load()
        if bundle_id in data["explicit_removals"]:
            return EvidenceLevel.EXPLICIT_REMOVAL
        if bundle_id in data["applications"] and bundle_id not in current_ids:
            return EvidenceLevel.OBSERVED_MISSING
        return EvidenceLevel.EXACT_IDENTIFIER

    @staticmethod
    def _empty() -> dict:
        return {
            "schema_version": STATE_VERSION,
            "applications": {},
            "explicit_removals": {},
        }
