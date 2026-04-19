# -*- mode: python ; coding: utf-8 -*-
import platform


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('F_icon.png', '.'),
        ('F_icon.ico', '.'),
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
        'pystray._WIN32',
        'pystray._xtab',
        'ctypes',
        'requests',
        'dotenv',
        'subprocess',
        'mss',
        'mss.tools',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter','test'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64' if platform.system() == 'Darwin' else None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['F_icon.ico'],
)