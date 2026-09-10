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
]
binaries = []
hiddenimports = ['keyboard', 'pyaudio', 'pythonosc', 'numpy', 'webrtcvad']

tmp_ret = collect_all('sherpa_onnx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# 扬声器回环捕获（同传悬浮窗功能）
tmp_ret = collect_all('pyaudiowpatch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['vrc_osc_chat.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # hooks/ 覆盖 hooks-contrib 里损坏的 webrtcvad 元数据钩子
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    # 只需 onnxruntime 核心推理。collect_all 会连带收集 onnxruntime.transformers，
    # 进而拉入 torch/transformers/sentencepiece 巨链，分析子进程 import 时崩溃
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
    name='VRChat_OSC_Chatbox_v4.3.2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)

