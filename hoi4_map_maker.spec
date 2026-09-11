# PyInstaller spec — package configuration for the HOI4 MOD creation tool.
# Usage: pyinstaller hoi4_map_maker.spec
# Output: dist/HOI4MapMaker/HOI4MapMaker.exe

# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Scan ui/i18n/<lang>/*.py dynamically and generate hidden imports.
# The English catalog is discovered automatically when the package is rebuilt.
_I18N_DIR = Path('ui/i18n')
_i18n_hiddenimports = [
    f'ui.i18n.{p.parent.name}.{p.stem}'
    for p in _I18N_DIR.glob('*/*.py')
    if p.stem != '__init__' and p.parent.is_dir() and not p.parent.name.startswith('_')
]


a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('data/atlas_tiles', 'data/atlas_tiles'),
        ('ui/i18n', 'ui/i18n'),
        # qdarktheme's internal .qss templates and .svg icons are needed at runtime.
        *collect_data_files('qdarktheme'),
        # resources/ contains local assets that are not committed; its absence
        # should not block packaging because it only affects the executable icon.
        *([('resources', 'resources')] if os.path.exists('resources') else []),
    ],
    hiddenimports=[
        # Features are loaded dynamically through importlib, so PyInstaller's
        # static analysis cannot discover them. Collect the whole package so new
        # features do not require another allowlist entry.
        *collect_submodules('features'),
        'scipy.ndimage',
        'scipy.spatial',
        # The distribution is named pyqtdarktheme but the import is qdarktheme;
        # declare the runtime module explicitly for PyInstaller.
        'qdarktheme',
        *_i18n_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # The project uses PyQt5 only. Exclude other Qt bindings so PyInstaller
        # does not bundle conflicting frameworks.
        'PySide6', 'PySide2', 'PyQt6', 'qt_material',
        'pytest', 'pytest_qt', 'tests',
        'torch', 'torchvision', 'torchaudio',
        'paddle', 'paddlepaddle',
        'cv2', 'opencv-python',
        'transformers', 'huggingface_hub',
        'onnxruntime', 'onnx',
        'llvmlite', 'numba',
        'av',
        'tensorflow', 'keras',
        'matplotlib', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HOI4MapMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,     # The release executable does not display a console.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icon.ico' if os.path.exists('resources/icon.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HOI4MapMaker',
)
