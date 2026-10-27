# -*- mode: python ; coding: utf-8 -*-
"""Distribución Windows 11: Qt en ventana, carpeta única (onedir), como LANWatch."""

from pathlib import Path
import shutil

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

project_root = Path(SPECPATH)

# demoparser2 está escrito en Rust e importa polars desde adentro: PyInstaller no lo ve solo.
polars_datas, polars_binaries, polars_hidden = [], [], []
for package in ('polars', 'polars_runtime_32'):
    datas_, binaries_, hidden_ = collect_all(package)
    polars_datas += datas_; polars_binaries += binaries_; polars_hidden += hidden_

a = Analysis(
    [str(project_root / 'desktop_entry.py')],
    pathex=[str(project_root)],
    binaries=collect_dynamic_libs('demoparser2') + polars_binaries,
    # El ayudante de Steam (Node.js + steam-user/globaloffensive/steam-session) viaja en la carpeta helper.
    datas=[(str(project_root / 'assets' / 'cs2stats.ico'), 'assets'),
           (str(project_root / 'cs2stats' / 'data' / 'latas.json'), 'cs2stats/data'),
           (str(project_root / 'helper' / 'helper.js'), 'helper'),
           (str(project_root / 'helper' / 'package.json'), 'helper'),
           (str(project_root / 'helper' / 'node_modules'), 'helper/node_modules'),
           (shutil.which('node'), 'helper')] + polars_datas,
    hiddenimports=['demoparser2', 'zstandard', 'pyarrow', 'pandas', 'polars', 'vpk', 'segno', 'PySide6.QtSvg',
                   'windows_capture', 'cv2', 'numpy'] + polars_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
        'PySide6.QtWebChannel', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtQuick', 'PySide6.QtQml',
        'PySide6.QtQuickWidgets', 'PySide6.QtPositioning', 'tkinter', 'matplotlib', 'IPython',
    ],
    noarchive=False,
    optimize=0,
)

# Igual que en LANWatch: si Poppler está en el PATH, PyInstaller puede recoger su icuuc.dll
# incompatible con Qt. Windows 11 trae la suya en System32; no se distribuye el homónimo.
excluded_icu_binaries = {'icuuc.dll', 'icudt78.dll'}
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.casefold() not in excluded_icu_binaries]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CS2Stats',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(project_root / 'assets' / 'cs2stats.ico')],
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name='CS2Stats')
