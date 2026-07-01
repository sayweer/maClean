"""Sabitler: tarama konumları, güvenlik listeleri ve eşikler.

Bu dosyanın tamamı VERİdir — mantık içermez. Böylece hem okunması hem de
testlerde referans alınması kolaydır. Tek iç bağımlılığı, konumları
kategorilere bağlamak için kullanılan ResidueCategory enum'udur.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import ResidueCategory

HOME = Path.home()

# --- Yüklü uygulama tespiti ------------------------------------------------

# Yüklü .app bundle'larının aranacağı kökler.
# /System/Applications KASITLI OLARAK dışarıda: Apple'ın kendi uygulamaları
# taranmaz (onlar zaten silinemez) ve sistem alanına hiç dokunulmaz.
APP_SCAN_ROOTS = [Path("/Applications"), HOME / "Applications"]

# --- Öksüz kalıntı tarama konumları ---------------------------------------

LIBRARY_ROOT = HOME / "Library"

# Taranacak her ~/Library alt konumu ve ait olduğu kategori.
# Sudo gerektiren sistem geneli konumlar (/Library/LaunchAgents vb.) v1
# kapsamı dışıdır — yalnızca kullanıcı seviyesi ~/Library taranır.
SCAN_LOCATIONS: dict[ResidueCategory, Path] = {
    ResidueCategory.CACHE:               LIBRARY_ROOT / "Caches",
    ResidueCategory.APPLICATION_SUPPORT: LIBRARY_ROOT / "Application Support",
    ResidueCategory.PREFERENCES:         LIBRARY_ROOT / "Preferences",
    ResidueCategory.LOGS:                LIBRARY_ROOT / "Logs",
    ResidueCategory.SAVED_STATE:         LIBRARY_ROOT / "Saved Application State",
    ResidueCategory.CONTAINERS:          LIBRARY_ROOT / "Containers",
    ResidueCategory.GROUP_CONTAINERS:    LIBRARY_ROOT / "Group Containers",
    ResidueCategory.WEBKIT:              LIBRARY_ROOT / "WebKit",
    ResidueCategory.HTTP_STORAGES:       LIBRARY_ROOT / "HTTPStorages",
    ResidueCategory.APPLICATION_SCRIPTS: LIBRARY_ROOT / "Application Scripts",
}

# İsim bazlı bulanık eşleştirmeye (Strateji B) izin verilen konumlar.
# Buralarda geliştiriciler klasörü genelde görünen adla ("Sublime Text")
# adlandırır, bundle-id ile değil.
NAME_FUZZY_LOCATIONS: frozenset[ResidueCategory] = frozenset({
    ResidueCategory.CACHE,
    ResidueCategory.APPLICATION_SUPPORT,
    ResidueCategory.LOGS,
})

# En az anlaşılan / en riskli konumlar. Burada yalnızca kesin bundle-id
# eşleşmesi denenir; belirsizlik varsa öğe sessizce atlanır (fuzzy fallback YOK).
CAUTIOUS_LOCATIONS: frozenset[ResidueCategory] = frozenset({
    ResidueCategory.GROUP_CONTAINERS,
    ResidueCategory.APPLICATION_SCRIPTS,
})

# --- Eşleştirme desenleri ve güvenlik listeleri ---------------------------

# Ters-DNS benzeri bundle-id deseni (en az bir nokta): com.vendor.app
BUNDLE_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$"
)

# ASLA öksüz sayılmayacak bundle-id önekleri (küçük harfle karşılaştırılır).
# Kritik: /System/Applications taranmadığı için Apple'ın kendi uygulamalarının
# bundle-id'leri "yüklü" setimizde hiç görünmez. Bu koruma olmadan onların
# ~/Library kalıntıları YANLIŞLIKLA öksüz işaretlenir. Bu, eşleştirme
# mantığından bağımsız, en son uygulanan bir "hard override" filtresidir.
PROTECTED_BUNDLE_PREFIXES = ("com.apple.",)

# Birden fazla ürünün paylaştığı "şemsiye" klasörler (küçük harfle).
# Kendileri asla aday sayılmaz; bir seviye içine inilip alt klasörler
# değerlendirilir. Böylece bir Adobe ürünü hâlâ yüklüyken "Adobe" klasörünü
# toptan öksüz sanma riski önlenir.
VENDOR_UMBRELLA_FOLDERS = frozenset({
    "adobe", "google", "microsoft", "mozilla", "jetbrains",
})

# difflib.SequenceMatcher.ratio() için isim eşleşme eşiği.
FUZZY_MATCH_THRESHOLD = 0.85

# Kalıntı adlarından soyulup alttaki bundle-id'yi ortaya çıkaran uzantılar
# (ör. "com.foo.bar.plist" -> "com.foo.bar", "...savedState" -> "...").
STRIP_SUFFIXES = (".savedState", ".binarycookies", ".plist")

# Group Containers adlarındaki bilinen önek (soyulup bundle-id olarak denenir):
# "group.com.foo.bar" -> "com.foo.bar".
GROUP_CONTAINER_PREFIXES = ("group.",)

# Bilinen geliştirici aracı / paket yöneticisi önbellekleri. Bunlar silinmiş
# uygulama kalıntısı DEĞİL, aktif kullanılan araçların önbellekleridir; adı
# (küçük harf) bu kümede olan öğe asla öksüz önerilmez. Liste bilinçli olarak
# kısa tutulur — kapsamlı olmak hedeflenmez, en sık rastlanan gürültü elenir.
KNOWN_TOOL_CACHES = frozenset({
    "pip", "homebrew", "node-gyp", "npm", "yarn", "pnpm",
    "go", "go-build", "deno", "cargo", "typescript",
    "ms-playwright", "ms-playwright-go", "puppeteer",
})
