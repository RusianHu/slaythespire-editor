# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPEC).resolve().parent
exe_name = os.environ.get("STS2_EXE_BASENAME", "slaythespire-editor-sts2")
version_file = os.environ.get("STS2_PYINSTALLER_VERSION_FILE")

hiddenimports = sorted(set(collect_submodules("sts2")))
excludes = [
    "torch",
    "torchaudio",
    "torchvision",
    "torchgen",
    "triton",
    "tensorflow",
    "tensorboard",
    "jax",
    "jaxlib",
    "onnx",
    "onnxruntime",
]

analysis = Analysis(
    [str(project_root / "editor_sts2.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=None)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    version=version_file,
)

