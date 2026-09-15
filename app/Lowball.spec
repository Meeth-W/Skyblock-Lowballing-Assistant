# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the desktop app.

One-folder rather than one-file. A one-file build unpacks the whole of Qt to a
temporary directory on every launch, which costs several seconds before the
window appears -- and this app is opened while a customer is standing there.
The folder also lets a user see what they downloaded, which matters for
something that watches a game they can be banned from.

Windowed, so double-clicking does not leave a console behind. The diagnostic
modes are still reachable from a terminal:

    Lowball.exe --listen        print what the mod sends, no window
    Lowball.exe --demo          synthetic data, no mod and no network

    pyinstaller Lowball.spec --noconfirm
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Three files the package reads at runtime through `Path(__file__).with_name`,
# so they have to land beside their module in the bundle and not merely be
# present somewhere in it.
datas = [
    ("lowball/ledger/schema.sql", "lowball/ledger"),
    ("lowball/ledger/projections.sql", "lowball/ledger"),
    ("lowball/rules/defaults.yaml", "lowball/rules"),
]
binaries = []
hiddenimports = [
    # Reached only through a deferred import inside main(), which the analysis
    # follows, but naming them makes a missing one a build failure rather than
    # a traceback on a user's machine.
    "lowball.listen",
    "lowball.demo",
    # Charts are imported lazily by the statistics view.
    "lowball.ui.charts",
]

# ruamel.yaml is a namespace package and loads its round-trip machinery
# dynamically; collecting it whole is cheaper than chasing which half the
# settings writer happens to touch.
for package in ("ruamel.yaml", "pyqtgraph", "nbtlib"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# websockets picks its implementation at import time from what is installed.
hiddenimports += collect_submodules("websockets")

a = Analysis(
    ["entrypoint.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt ships several large modules this app never touches, and matplotlib is
    # an optional extra for the report script rather than part of the product.
    excludes=[
        "matplotlib",
        "tkinter",
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtQuick3D",
        "PySide6.QtMultimedia",
        "PySide6.QtBluetooth",
        "PySide6.QtDesigner",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lowball",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Lowball",
)
