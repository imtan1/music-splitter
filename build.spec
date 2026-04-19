# -*- mode: python ; coding: utf-8 -*-
import sys
sys.setrecursionlimit(5000)
"""
PyInstaller 打包設定
執行前請確認：
  1. 在 venv 環境中執行（不要用系統 Python）
  2. 已安裝所有 requirements.txt 的套件
  3. pip install pyinstaller
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

# ──────────────────────────────────────────────
# 收集各套件的資料與二進位檔
# ──────────────────────────────────────────────

all_datas    = []
all_binaries = []
all_hidden   = []

for pkg in ['demucs', 'librosa', 'audioread', 'soundfile', 'resampy',
            'soxr', 'lazy_loader', 'msgpack', 'verovio', 'music21']:
    d, b, h = collect_all(pkg)
    all_datas    += d
    all_binaries += b
    all_hidden   += h

# matplotlib 後端
for pkg in ['matplotlib']:
    d, b, h = collect_all(pkg)
    all_datas    += d
    all_binaries += b
    all_hidden   += h

# torch / torchaudio / demucs metadata（importlib.metadata 需要）
for pkg in ['torch', 'torchaudio', 'demucs']:
    try:
        all_datas += copy_metadata(pkg)
    except Exception:
        pass

# 應用程式自身資料檔
all_datas += [
    ('ui/styles.qss', 'ui'),
    ('assets',        'assets'),
]

# ──────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden + [
        # Audio
        'sounddevice',
        'soundfile',
        'pydub',
        'pydub.utils',
        'soxr',
        # Torch（需 --copy-metadata torch）
        'torch',
        'torch.nn',
        'torchaudio',
        'torchaudio.transforms',
        # Scientific
        'numpy',
        'scipy',
        'scipy.signal',
        'scipy.fft',
        'sklearn',
        'sklearn.preprocessing',
        'numba',
        'llvmlite',
        # Qt
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtMultimedia',
        # Matplotlib
        'matplotlib.backends.backend_agg',
        'matplotlib.pyplot',
        # Demucs
        'demucs.pretrained',
        'demucs.apply',
        'demucs.audio',
        # Standard library (dynamically imported by torch.distributed)
        'unittest',
        'unittest.mock',
        'distutils',
        'distutils.version',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'PyQt5', 'PyQt6', 'PySide2',
        'IPython', 'jupyter', 'notebook',
        'test', 'xmlrunner',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MusicSplitter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # 不顯示黑色 cmd 視窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icons/app.ico',  # 取消註解並提供 .ico 圖示檔
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'msvcp140.dll', 'Qt6Core.dll'],
    name='MusicSplitter',
)
