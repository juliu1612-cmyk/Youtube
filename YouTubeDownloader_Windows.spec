# -*- mode: python ; coding: utf-8 -*-
"""Windows build spec for YouTube Downloader.
Run: pyinstaller YouTubeDownloader_Windows.spec --noconfirm --clean
"""
import os
import sys
from PyInstaller.utils.hooks import collect_all

# Base directory = where this spec file lives
BASE_DIR = os.path.dirname(os.path.abspath(SPEC))

datas = [(os.path.join(BASE_DIR, 'index.html'), '.')]
binaries = []
hiddenimports = ['yt_dlp']

# yt-dlp
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pywebview (Windows uses EdgeChromium / WebView2 backend)
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pythonnet (pywebview dependency on Windows for .NET interop)
try:
    tmp_ret = collect_all('clr')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass
try:
    tmp_ret = collect_all('pythonnet')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

# WebView2 loader DLL if present
try:
    import clr_loader
    tmp_ret = collect_all('clr_loader')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass


a = Analysis(
    [os.path.join(BASE_DIR, 'server.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YouTubeDownloader',
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
    name='YouTubeDownloader',
)
