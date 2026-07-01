"""Çekirdek tespit mantığı: yüklü uygulamalar ve öksüz kalıntılar.

Bu modül Tkinter'dan tamamen bağımsızdır; GUI olmadan test edilebilir.
"""

from __future__ import annotations

import logging
import os
import plistlib
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable

from . import constants
from .models import MatchConfidence, OrphanItem, ResidueCategory

logger = logging.getLogger(__name__)


# ==========================================================================
# Bölüm 1 — Yüklü uygulama tespiti
# ==========================================================================

def _read_bundle(app_path: Path) -> tuple[str, str] | None:
    """Bir .app bundle'ından (bundle_id_küçük_harf, görünen_ad) döndürür.

    Bundle okunamaz/kimliksizse None döner. Tek bir bozuk bundle asla tüm
    taramayı durdurmamalı — bu yüzden okuma hataları yutulup loglanır.
    """
    info_plist = app_path / "Contents" / "Info.plist"
    try:
        with open(info_plist, "rb") as f:
            plist = plistlib.load(f)
    except FileNotFoundError:
        # .app ile biten ama geçerli Info.plist'i olmayan klasör — sessizce atla.
        return None
    except Exception as exc:  # noqa: BLE001 - bkz. docstring: dayanıklılık > kesinlik
        logger.warning("Info.plist okunamadı: %s (%s)", info_plist, exc)
        return None

    bundle_id = plist.get("CFBundleIdentifier")
    if not isinstance(bundle_id, str) or not bundle_id:
        return None

    name = (
        plist.get("CFBundleDisplayName")
        or plist.get("CFBundleName")
        or app_path.name.removesuffix(".app")
    )
    return bundle_id.lower(), str(name)


def discover_installed_apps(
    app_scan_roots: list[Path] | None = None,
) -> tuple[set[str], dict[str, str]]:
    """Yüklü uygulamaları tarar.

    Döndürür: (küçük_harf_bundle_id_seti, {bundle_id: görünen_ad}).

    /System/Applications KESİNLİKLE taranmaz (bkz. constants.APP_SCAN_ROOTS).
    Bir .app bundle'ının İÇİNE inilmez: içteki yardımcı bundle'lar (ör. bir
    tarayıcının Frameworks altındaki yardımcı süreçleri) ayrı uygulama sayılmaz.
    """
    if app_scan_roots is None:
        app_scan_roots = constants.APP_SCAN_ROOTS

    installed_ids: set[str] = set()
    name_by_id: dict[str, str] = {}

    for root in app_scan_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, _filenames in os.walk(root):
            app_dirs = [d for d in dirnames if d.endswith(".app")]
            # Budama: .app bundle'larının içine inme.
            dirnames[:] = [d for d in dirnames if not d.endswith(".app")]
            for app_dir in app_dirs:
                result = _read_bundle(Path(dirpath) / app_dir)
                if result is None:
                    continue
                bundle_id, name = result
                installed_ids.add(bundle_id)
                name_by_id[bundle_id] = name

    return installed_ids, name_by_id


# ==========================================================================
# Bölüm 2 — Öksüz kalıntı tespiti
# ==========================================================================

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    """Bulanık karşılaştırma için: küçük harf + alfanümerik dışını at."""
    return _NON_ALNUM.sub("", text.lower())


def _strip_suffixes(name: str) -> str:
    for suffix in constants.STRIP_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _strip_group_prefix(name: str) -> str:
    for prefix in constants.GROUP_CONTAINER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _looks_like_version(text: str) -> bool:
    """Nokta içeren ama gerçek bundle-id olmayan sürüm/isim adını yakalar.

    'AndroidStudio2024.3.2' gibi adlar noktalar yüzünden bundle-id desenine
    uyar ama değildir. Gerçek reverse-DNS bundle-id'lerinde tamamen sayısal
    segment (ör. '.3', '.2') pratikte bulunmaz; sürüm klasörlerinde bulunur.
    """
    return any(segment.isdigit() for segment in text.split("."))


def _prettify_bundle_id(bundle_id: str) -> str:
    """Bundle-id'nin son segmentinden okunabilir bir ad tahmin eder.

    'com.adobe.PhotoshopElements' -> 'Photoshop Elements'. Yalnızca bir
    tahmindir; GUI'de ham bundle-id ve tam yol da her zaman gösterilir.
    """
    last = bundle_id.split(".")[-1]
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", last)
    spaced = spaced.replace("-", " ").replace("_", " ").strip()
    return spaced or bundle_id


def _safe_scandir(path: Path) -> list[os.DirEntry]:
    """os.scandir'ı hataya dayanıklı sarar; izin/okuma hatasında boş liste."""
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError as exc:
        logger.warning("Konum taranamadı: %s (%s)", path, exc)
        return []


def _dir_size(path: Path) -> int:
    """Bir dizinin özyinelemeli toplam boyutu; erişilemeyen alt öğeler atlanır."""
    total = 0
    for entry in _safe_scandir(path):
        try:
            if entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(Path(entry.path))
        except OSError:
            continue
    return total


def _entry_size(entry: os.DirEntry) -> int:
    try:
        if entry.is_symlink():
            return 0
        if entry.is_file(follow_symlinks=False):
            return entry.stat(follow_symlinks=False).st_size
        if entry.is_dir(follow_symlinks=False):
            return _dir_size(Path(entry.path))
    except OSError:
        return 0
    return 0


def _within(path: Path, base: Path) -> bool:
    """path, base'in altında (ya da eşiti) mi? — sembolik link kaçışına karşı."""
    try:
        return path == base or path.is_relative_to(base)
    except (OSError, ValueError):
        return False


def _has_installed_suffix(bundle_id_lower: str, installed_ids: set[str]) -> bool:
    """Aday, yüklü bir bundle-id'nin takım-kimliği önekli hali mi?

    Örn. Application Scripts altında 'ABCDE12345.com.foo.bar' — altta yatan
    'com.foo.bar' yüklüyse öksüz sayılmamalı.
    """
    return any(bundle_id_lower.endswith("." + iid) for iid in installed_ids)


def _has_installed_prefix(bundle_id_lower: str, installed_ids: set[str]) -> bool:
    """Aday, yüklü bir uygulamanın alt-namespace'i mi?

    Yardımcı süreçler ve güncelleyiciler bundle-id'lerini ana uygulamanınkine
    ekleyerek türetir: 'com.foo.bar' yüklüyken 'com.foo.bar.ShipIt' (Squirrel)
    veya 'com.foo.bar.helper'. Bunlar ana uygulama yüklü olduğu sürece öksüz
    DEĞİLdir. Yalnızca yanlış pozitifleri azaltır: 'com.foo.baz' gibi kardeş
    kimlikler nokta sınırı nedeniyle etkilenmez, gerçek öksüzler gizlenmez.
    """
    return any(bundle_id_lower.startswith(iid + ".") for iid in installed_ids)


def _fuzzy_matches_installed(
    candidate_norms: list[str], installed_norms: set[str]
) -> bool:
    for cand in candidate_norms:
        if not cand:
            continue
        for inst in installed_norms:
            if not inst:
                continue
            if cand == inst:
                return True
            if SequenceMatcher(None, cand, inst).ratio() >= constants.FUZZY_MATCH_THRESHOLD:
                return True
    return False


def _build_item(
    entry: os.DirEntry,
    category: ResidueCategory,
    display_name: str,
    bundle_id: str | None,
    confidence: MatchConfidence,
    base_resolved: Path,
) -> list[OrphanItem]:
    """Bir aday için OrphanItem üretir; ~/Library dışına çıkanı savunma amaçlı eler."""
    path = Path(entry.path)
    try:
        resolved = path.resolve()
    except OSError:
        return []
    if not _within(resolved, base_resolved):
        logger.warning("Aday tarama kökü dışında, atlandı: %s", path)
        return []

    try:
        mtime = datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime)
    except OSError:
        mtime = datetime.fromtimestamp(0)

    return [OrphanItem(
        display_name=display_name,
        bundle_id=bundle_id,
        category=category,
        path=path,
        size_bytes=_entry_size(entry),
        last_modified=mtime,
        confidence=confidence,
    )]


def _classify(
    entry: os.DirEntry,
    category: ResidueCategory,
    installed_ids: set[str],
    installed_norms: set[str],
    base_resolved: Path,
    vendor_prefix: str | None = None,
) -> list[OrphanItem]:
    """Tek bir kalıntı adayını sınıflandırır: öksüzse OrphanItem, değilse boş liste."""
    # Bilinen geliştirici aracı önbelleği ise hiç değerlendirme (asla önerme).
    if entry.name.lower() in constants.KNOWN_TOOL_CACHES:
        return []

    # Klasör adı görünen addan sapan bilinen uygulama (ör. VS Code -> "Code"):
    # eşlenen bundle-id yüklüyse öksüz değil; yüklü değilse normal mantık işler.
    alias_id = constants.KNOWN_APP_DATA_ALIASES.get(entry.name.lower())
    if alias_id is not None and alias_id in installed_ids:
        return []

    candidate = _strip_suffixes(entry.name)
    cautious = category in constants.CAUTIOUS_LOCATIONS
    lookup = _strip_group_prefix(candidate) if cautious else candidate

    # --- Strateji A: bundle-id eşleşmesi ---
    if constants.BUNDLE_ID_PATTERN.match(lookup) and not _looks_like_version(lookup):
        lower = lookup.lower()
        # Son koruma katmanı: Apple sistem bileşenlerine asla dokunma.
        if lower.startswith(constants.PROTECTED_BUNDLE_PREFIXES):
            return []
        if lower in installed_ids:
            return []  # yüklü → öksüz değil
        if _has_installed_prefix(lower, installed_ids):
            return []  # yüklü uygulamanın yardımcısı/güncelleyicisi (alt-namespace)
        if cautious and _has_installed_suffix(lower, installed_ids):
            return []  # takım-kimliği önekli ama alttaki uygulama yüklü
        # Kısa, bundle-id GÖRÜNÜMLÜ adlar aslında uygulama adı olabilir:
        # Zoom yüklüyken "zoom.us" klasörü desene uyar ama kimlik değildir
        # (gerçek kimlik us.zoom.xos). Yüklü bir uygulama adıyla eşleşiyorsa
        # öksüz sayma — bu veto yalnızca işaretlemeyi engeller, asla eklemez.
        if _fuzzy_matches_installed([_normalize(lookup)], installed_norms):
            return []
        return _build_item(
            entry, category, _prettify_bundle_id(lookup), lower,
            MatchConfidence.BUNDLE_ID, base_resolved,
        )

    # --- Ad bundle-id deseninde değil ---
    if cautious:
        return []  # temkinli konumda bulanık fallback yok

    if category in constants.NAME_FUZZY_LOCATIONS:
        candidate_norms = [_normalize(candidate)]
        if vendor_prefix:
            candidate_norms.append(_normalize(f"{vendor_prefix} {candidate}"))
        if not any(candidate_norms):
            # Ad tamamen latin-alfanümerik dışı (ör. Korece/Çince uygulama):
            # normalizasyon boş kaldı, karşılaştıracak sinyal yok → karar verme.
            return []
        if _fuzzy_matches_installed(candidate_norms, installed_norms):
            return []  # yüklü bir uygulamayla eşleşti → öksüz değil
        display = f"{vendor_prefix} — {candidate}" if vendor_prefix else candidate
        return _build_item(
            entry, category, display, None,
            MatchConfidence.NAME_FUZZY, base_resolved,
        )

    # Strateji A-only konum (Preferences, Containers, WebKit, HTTPStorages,
    # Saved State) ve ad bundle-id deseninde değil → güvenle karar veremeyiz.
    return []


def _evaluate_entry(
    entry: os.DirEntry,
    category: ResidueCategory,
    installed_ids: set[str],
    installed_norms: set[str],
    base_resolved: Path,
) -> list[OrphanItem]:
    """Bir üst düzey kalıntı öğesini değerlendirir; vendor şemsiyesini açar."""
    is_umbrella = (
        category in constants.NAME_FUZZY_LOCATIONS
        and entry.name.lower() in constants.VENDOR_UMBRELLA_FOLDERS
    )
    if is_umbrella and _is_dir(entry):
        # Şemsiye klasörün KENDİSİ asla aday olmaz; bir seviye içine in.
        results: list[OrphanItem] = []
        for sub in _safe_scandir(Path(entry.path)):
            results.extend(_classify(
                sub, category, installed_ids, installed_norms,
                base_resolved, vendor_prefix=entry.name,
            ))
        return results

    return _classify(entry, category, installed_ids, installed_norms, base_resolved)


def _is_dir(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def find_orphans(
    installed_ids: set[str],
    installed_names: Iterable[str],
    library_root: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> list[OrphanItem]:
    """~/Library'yi tarayıp silinmiş uygulamalara ait kalıntıları bulur.

    installed_ids / installed_names, discover_installed_apps çıktısından gelir.
    library_root testler için enjekte edilebilir (varsayılan: ~/Library).
    Yalnızca salt okunur işlem yapar — hiçbir dosyaya dokunmaz.
    """
    lib_root = library_root if library_root is not None else constants.LIBRARY_ROOT
    base_resolved = lib_root.resolve()
    installed_norms = {_normalize(n) for n in installed_names}

    orphans: list[OrphanItem] = []
    for category, default_path in constants.SCAN_LOCATIONS.items():
        # Konumu enjekte edilen library_root altında yeniden kur.
        location = lib_root / default_path.name
        if progress_callback:
            progress_callback(category.value)
        if not location.is_dir():
            continue
        for entry in _safe_scandir(location):
            orphans.extend(_evaluate_entry(
                entry, category, installed_ids, installed_norms, base_resolved,
            ))

    return orphans
