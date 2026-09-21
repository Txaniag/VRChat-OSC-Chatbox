# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx',
     'models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17'),
    ('models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt',
     'models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17'),
    ('models/silero_vad.onnx', 'models'),
    ('models/gtcrn_simple.onnx', 'models'),
    ('app_icon.ico', '.'),
    ('edge_host/bin/Release/net8.0-windows/win-x64/publish', 'edge_host'),
]
binaries = []
hiddenimports = ['keyboard', 'pyaudio', 'pythonosc', 'numpy', 'webrtcvad']

tmp_ret = collect_all('sherpa_onnx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyaudiowpatch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['vrc_osc_chat.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'onnxruntime.transformers',
        'torch', 'transformers', 'sentencepiece', 'sacremoses', 'tokenizers',
        'scipy', 'matplotlib', 'pandas', 'IPython', 'jedi', 'tkinter',
        'cv2', 'sklearn', 'sounddevice',
    ],
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
    name='VRChat_debug',
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
