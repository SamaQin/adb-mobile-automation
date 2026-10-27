# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[
        ("adb.exe", "."),
        ("AdbWinApi.dll", "."),
        ("AdbWinUsbApi.dll", "."),
    ],
    datas=[
        ("web/dist", "web/dist"),
        ("vendor/scrcpy-server-v5.0.1", "vendor"),
    ],
    hiddenimports=(
        collect_submodules("fastapi")
        + collect_submodules("uvicorn")
        + collect_submodules("websockets")
    ),
    hookspath=[],
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
    name="ADB-Automation",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ADB-Automation",
)
