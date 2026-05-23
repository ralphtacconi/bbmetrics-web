# -*- mode: python ; coding: utf-8 -*-

# NOTE:
# We also copy in/users.csv explicitly into dist/BBMetrics_UI/in/users.csv
# in build_ui_exe.ps1, to guarantee the ZIP has an editable file before first run.

datas = [
    ("in\\users.csv", "in"),
]

a = Analysis(
    ["BBMetrics_UI\\app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    name="BBMetrics_UI",
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
    icon=["BBMetrics_UI\\assets\\app.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BBMetrics_UI",
)