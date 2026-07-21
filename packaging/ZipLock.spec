# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

datas = []
binaries = []
hiddenimports = []
for pkg in ("tkinterdnd2", "pyzipper"):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [os.path.join(PROJECT_ROOT, 'main_gui.py')],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Zip Lock',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Zip Lock',
)
# BUNDLE (.app wrapping) is macOS-only; on Windows the build ends at COLLECT,
# leaving dist/Zip Lock/Zip Lock.exe -- same onedir layout, no bundle.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name='Zip Lock.app',
        icon=None,
        bundle_identifier='com.dmallard.lockingzip',
    )
