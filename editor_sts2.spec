# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPEC).resolve().parent

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
    name="slaythespire-editor-sts2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)

