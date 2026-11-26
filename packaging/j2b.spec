# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for J2B Studio.

Build (on Windows, Python 3.10+ 64-bit):

    pip install -q pyinstaller
    python -m PyInstaller packaging/j2b.spec

Result: dist/J2BStudio.exe  (one-file, windowed, no console)
"""

import os
import sys

block_cipher = None

HERE = os.path.abspath(SPECPATH)
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Bundle the knowledge base next to the code so the frozen exe can read it.
datas = [
    (os.path.join(ROOT, "j2b", "knowledge", "data"), os.path.join("j2b", "knowledge", "data")),
]
readme = os.path.join(ROOT, "README.md")
if os.path.exists(readme):
    datas.append((readme, "."))

a = Analysis(
    [os.path.join(ROOT, "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "sqlite3",
        "zipfile",
        "zlib",
        "struct",
        "uuid",
        "json",
        "j2b.gui",
        "j2b.cli",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "pandas", "PIL", "matplotlib", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="J2BStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed: the GUI is the entry point
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(HERE, "icon.ico") if os.path.exists(os.path.join(HERE, "icon.ico")) else None,
)
