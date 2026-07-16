"""Seçilen uygulama için güvenli kaldırma planı ve işlem yürütücüsü."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from . import constants, trash
from .applications import (
    enrich_application_groups,
    is_application_running,
    validate_removable_application,
)
from .models import (
    ApplicationRecord,
    DataKind,
    EvidenceLevel,
    RemovalItem,
    RemovalMode,
    RemovalPlan,
    RemovalResult,
    ResidueCategory,
    ScanIssue,
    file_identity,
    identity_matches,
)
from .scanner import measure_path
from .state import StateStore

STANDARD_CATEGORIES = frozenset(
    {
        ResidueCategory.CACHE,
        ResidueCategory.LOGS,
        ResidueCategory.SAVED_STATE,
        ResidueCategory.WEBKIT,
        ResidueCategory.HTTP_STORAGES,
    }
)
FULL_PRIVATE_CATEGORIES = frozenset(
    {
        ResidueCategory.PREFERENCES,
        ResidueCategory.APPLICATION_SUPPORT,
        ResidueCategory.CONTAINERS,
    }
)
SHARED_CATEGORIES = frozenset(
    {ResidueCategory.GROUP_CONTAINERS, ResidueCategory.APPLICATION_SCRIPTS}
)
_NON_ALNUM = re.compile(r"[^\w]+", re.UNICODE)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return _NON_ALNUM.sub("", value)


def _candidate_identifier(name: str) -> str:
    lowered = name.casefold()
    for suffix in constants.STRIP_SUFFIXES:
        if lowered.endswith(suffix.casefold()):
            lowered = lowered[: -len(suffix)]
            break
    return lowered.removeprefix("group.")


def _entry_metadata(path: Path) -> tuple[int | None, datetime, tuple[ScanIssue, ...]]:
    size, issues = measure_path(path)
    try:
        modified = datetime.fromtimestamp(path.stat(follow_symlinks=False).st_mtime)
    except OSError as exc:
        issues = (*issues, ScanIssue(path, str(exc), "stat"))
        modified = datetime.fromtimestamp(0)
    return size, modified, issues


def _group_owners(
    applications: list[ApplicationRecord],
    target_groups: frozenset[str],
) -> dict[str, set[str]]:
    if not target_groups:
        return {}
    owners: dict[str, set[str]] = {}
    for application in applications:
        # System protectors cannot share a third-party application group because
        # group identifiers are scoped to the signing team. Avoid hundreds of
        # unnecessary codesign subprocesses on every plan build.
        if not application.selectable:
            continue
        enriched = (
            application
            if application.application_groups
            else enrich_application_groups(application)
        )
        for group in set(enriched.application_groups) & target_groups:
            owners.setdefault(group.casefold(), set()).add(enriched.bundle_id)
    return owners


def build_removal_plan(
    application: ApplicationRecord,
    mode: RemovalMode,
    installed_applications: list[ApplicationRecord],
    *,
    library_root: Path | None = None,
) -> RemovalPlan:
    validation_error = validate_removable_application(application)
    if validation_error:
        raise ValueError(validation_error)
    if not application.application_groups:
        application = enrich_application_groups(application)
    app_identity = file_identity(application.path)
    if app_identity is None:
        raise ValueError("Uygulama paketi artık mevcut değil veya okunamıyor.")

    lib_root = library_root or constants.LIBRARY_ROOT
    all_ids = {identifier.casefold() for identifier in application.all_bundle_ids}
    app_names = {
        _normalize(application.name),
        _normalize(application.path.stem),
    }
    target_groups = frozenset(
        group.casefold() for group in application.application_groups
    )
    group_owners = _group_owners(installed_applications, target_groups)
    issues: list[ScanIssue] = []
    items: list[RemovalItem] = []

    for category, default_path in constants.SCAN_LOCATIONS.items():
        location = lib_root / default_path.name
        try:
            entries = list(os.scandir(location))
        except FileNotFoundError:
            continue
        except OSError as exc:
            issues.append(ScanIssue(location, str(exc), "access"))
            continue

        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                continue
            try:
                if not path.resolve().is_relative_to(lib_root.resolve()):
                    continue
            except (OSError, ValueError):
                continue

            raw_lower = entry.name.casefold()
            identifier = _candidate_identifier(entry.name)
            exact = identifier in all_ids
            exact_group = raw_lower in application.application_groups
            name_match = _normalize(entry.name) in app_names

            if category in SHARED_CATEGORIES:
                if not exact_group:
                    if not (exact or name_match):
                        continue
                    evidence = EvidenceLevel.SHARED_OR_UNKNOWN
                    selectable = False
                    selected = False
                    protected = "Paylaşılan alanın yalnız bu uygulamaya ait olduğu kanıtlanamadı."
                    reason = protected
                else:
                    owners = group_owners.get(raw_lower, {application.bundle_id})
                    exclusive = owners <= {application.bundle_id}
                    evidence = (
                        EvidenceLevel.EXACT_IDENTIFIER
                        if exclusive
                        else EvidenceLevel.SHARED_OR_UNKNOWN
                    )
                    selectable = exclusive and mode is RemovalMode.FULL
                    selected = selectable
                    protected = None if exclusive else "Başka bir kurulu uygulama da bu alanı kullanıyor."
                    reason = (
                        "Kod imzasındaki application-group yetkisiyle doğrulandı."
                        if exclusive
                        else protected
                    )
                data_kind = DataKind.SHARED
            elif exact:
                evidence = EvidenceLevel.EXACT_IDENTIFIER
                if category in STANDARD_CATEGORIES:
                    data_kind = DataKind.TRANSIENT
                    selectable = True
                    selected = True
                elif category in FULL_PRIVATE_CATEGORIES:
                    data_kind = DataKind.PERSISTENT
                    selectable = True
                    selected = mode is RemovalMode.FULL
                else:
                    continue
                protected = None
                reason = "Uygulama veya yardımcı bileşen bundle kimliğiyle eşleşti."
            elif name_match and category in constants.NAME_FUZZY_LOCATIONS:
                evidence = EvidenceLevel.NAME_ONLY
                data_kind = (
                    DataKind.TRANSIENT
                    if category in STANDARD_CATEGORIES
                    else DataKind.PERSISTENT
                )
                selectable = True
                selected = False
                protected = None
                reason = "Uygulama adıyla eşleşiyor; bundle kimliğiyle doğrulanamadı."
            else:
                continue

            size, modified, entry_issues = _entry_metadata(path)
            issues.extend(entry_issues)
            if size is None:
                selectable = False
                selected = False
                protected = "Öğe tamamen okunamadığı için seçilemez."
                reason += " Boyut ve içerik doğrulanamadı."
            items.append(
                RemovalItem(
                    display_name=entry.name,
                    path=path,
                    category=category,
                    size_bytes=size,
                    last_modified=modified,
                    evidence=evidence,
                    data_kind=data_kind,
                    reason=reason,
                    identity=file_identity(path),
                    selected_by_default=selected,
                    selectable=selectable,
                    protected_reason=protected,
                )
            )

    items.sort(
        key=lambda item: (
            item.evidence is EvidenceLevel.NAME_ONLY,
            -(item.size_bytes or 0),
        )
    )
    return RemovalPlan(
        application=application,
        mode=mode,
        application_identity=app_identity,
        items=tuple(items),
        issues=tuple(issues),
    )


def execute_removal(
    plan: RemovalPlan,
    selected_paths: set[Path] | frozenset[Path] | None = None,
    *,
    state_store: StateStore | None = None,
) -> RemovalResult:
    validation_error = validate_removable_application(plan.application)
    if validation_error:
        return RemovalResult(False, aborted_reason=validation_error)
    if is_application_running(plan.application):
        return RemovalResult(
            False,
            aborted_reason="Uygulama çalışıyor. Kapatıp tekrar deneyin.",
        )
    if not identity_matches(plan.application.path, plan.application_identity):
        return RemovalResult(
            False,
            aborted_reason="Uygulama taramadan sonra değişti; yeniden plan oluşturun.",
        )

    app_succeeded, app_failed = trash.move_to_trash([plan.application.path])
    if not app_succeeded:
        message = app_failed[0][1] if app_failed else "Bilinmeyen taşıma hatası."
        return RemovalResult(
            False,
            failed_paths=tuple(app_failed),
            aborted_reason=f"Uygulama Çöp'e taşınamadı: {message}",
        )

    chosen = plan.default_selected_paths if selected_paths is None else frozenset(selected_paths)
    moved: list[Path] = [plan.application.path]
    failed: list[tuple[Path, str]] = []
    for item in plan.items:
        if item.path not in chosen or not item.selectable:
            continue
        if item.identity is None or not identity_matches(item.path, item.identity):
            failed.append((item.path, "Öğe taramadan sonra değişti; güvenlik için atlandı."))
            continue
        succeeded, item_failed = trash.move_to_trash([item.path])
        moved.extend(succeeded)
        failed.extend(item_failed)

    store = state_store or StateStore()
    store.record_explicit_removal(plan.application, tuple(failed))
    return RemovalResult(
        True,
        moved_paths=tuple(moved),
        failed_paths=tuple(failed),
    )
