# -*- mode: python ; coding: utf-8 -*-
# ruff: noqa: F821  -- Analysis/PYZ/EXE/COLLECT/BUNDLE are injected by PyInstaller.
"""PyInstaller build for the 나만의빛 desktop app (macOS .app / Windows .exe)."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

APP_NAME = "나만의빛"
VERSION = (Path(SPECPATH) / "VERSION").read_text().strip()
IS_MAC = sys.platform == "darwin"
# codesign silently skips sealing a bundle whose CFBundleExecutable is not
# ASCII, so on macOS the inner binary keeps a plain name and only the bundle
# itself is 나만의빛.app. Windows has no such limit.
BINARY_NAME = "Namanuibit" if IS_MAC else APP_NAME

datas = [("static", "static"), ("assets/icon.png", "assets")]
binaries = []
# rawpy carries the LibRaw shared library next to its extension module.
hiddenimports = [
    "app",
    "adjustments",
    "engine",
    "paths",
    "xmp",
    "scipy.ndimage",
    "scipy._lib.array_api_compat.numpy.fft",
    "scipy.special._special_ufuncs",
    *collect_submodules("uvicorn"),
]
for package in ("rawpy", "webview"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "matplotlib", "IPython", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=BINARY_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=IS_MAC,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.icns" if IS_MAC else "assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=BINARY_NAME,
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon="assets/icon.icns",
        bundle_identifier="com.namanuibit.studio",
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "나만의빛 — 로컬 사진 스튜디오",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Image",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": [
                        "public.jpeg",
                        "public.png",
                        "public.tiff",
                        "public.camera-raw-image",
                        "com.adobe.raw-image",
                    ],
                }
            ],
        },
    )
