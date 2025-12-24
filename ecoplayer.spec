# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

added_files = [
		('static/images', 'static/images'),
		('icons', 'icons'),
		('static', 'static'),]

a = Analysis(
    ['ecoplayer.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=['librosa', 'numba', 'soundfile'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['PyQt6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
	exclude_binaries=True,
    name='ecoplayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='advanced_audio_player.ico')
coll = COLLECT(exe,
		   a.binaries,
		   a.zipfiles,
		   a.datas,
		   strip=False,
		   upx=True,
		   upx_exclude=[],
		   name='ecoplayer')
