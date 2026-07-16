# -*- mode: python ; coding: utf-8 -*-
"""maClean PyInstaller yapı tanımı — imzasız, onedir, windowed (.app).

customtkinter tema JSON'ları ve fontları pakete elle dahil edilir; aksi halde
paketlenen .app açıldığında tema bozuk/varsayılan görünür (bilinen tuzak).
"""

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

version_text = (Path(SPECPATH) / "maclean" / "__init__.py").read_text()
__version__ = re.search(r'__version__ = "([^"]+)"', version_text).group(1)

# customtkinter'ın tema/asset dosyalarını topla (kritik).
datas = collect_data_files("customtkinter")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="maClean",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # windowed — konsol penceresi yok
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,     # İMZASIZ (kararlaştırıldığı gibi)
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="maClean",
)

app = BUNDLE(
    coll,
    name="maClean.app",
    icon="assets/maclean.icns", # özel uygulama ikonu
    bundle_identifier="com.seyit.maclean",
    info_plist={
        "CFBundleName": "maClean",
        "CFBundleDisplayName": "maClean",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "NSHumanReadableCopyright": "© 2026 Seyit — MIT License",
        "NSHighResolutionCapable": True,
    },
)
