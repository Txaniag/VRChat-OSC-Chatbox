# -*- coding: utf-8 -*-
"""
VRChat OSC Chatbox Sender (PyQt5 + sherpa-onnx SenseVoice)
- 文字输入通过 OSC 发送至 VRChat
- 语音识别使用 SenseVoice 模型（中文/英文/日语/韩语/粤语）
- VAD 语音活动检测，说完自动识别并可自动发送
- 支持横屏/竖屏布局切换
- 完全离线，无需联网
"""

import sys
import os
import json
import datetime
import threading
import queue
import hashlib
import random
import urllib.request
import urllib.parse

import numpy as np
import pyaudio
import sherpa_onnx
import keyboard
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QCheckBox, QListWidget,
    QGroupBox, QStatusBar, QMessageBox, QComboBox, QRadioButton, QButtonGroup,
    QScrollArea, QFrame, QDialog, QSlider, QSpinBox, QFormLayout,
    QDialogButtonBox, QSplitter, QGraphicsBlurEffect
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPointF
from PyQt5.QtGui import QIcon, QPainter, QRadialGradient, QColor, QBrush, QLinearGradient
from pythonosc import udp_client

# ============================================================
# 路径处理
# ============================================================
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def resource_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = app_dir()
RES_DIR = resource_dir()
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
HISTORY_FILE = os.path.join(APP_DIR, "history.json")

# 模型路径
MODEL_DIR = os.path.join(RES_DIR, "models")
SENSEVOICE_DIR = os.path.join(MODEL_DIR, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")
ASR_MODEL = os.path.join(SENSEVOICE_DIR, "model.int8.onnx")
ASR_TOKENS = os.path.join(SENSEVOICE_DIR, "tokens.txt")
VAD_MODEL = os.path.join(MODEL_DIR, "silero_vad.onnx")

# ============================================================
# 常量
# ============================================================
APP_TITLE = "VRChat OSC Chatbox Sender"
APP_VERSION = "4.0.0"
DEFAULT_IP = "127.0.0.1"
DEFAULT_PORT = 9000
MAX_CHARS = 144
MAX_HISTORY = 50

SAMPLE_RATE = 16000
CHANNELS = 1
FRAMES_PER_BUFFER = 512  # Silero VAD 要求 512

# 语言映射
LANGUAGES = [
    ("自动检测", "auto"),
    ("中文", "zh"),
    ("英文", "en"),
    ("日语", "ja"),
    ("韩语", "ko"),
    ("粤语", "yue"),
]

# Apple 风格主题 - 基于 Apple Human Interface Guidelines
# 原则: 毛玻璃卡片, 极光背景, Bento Grid, 胶囊按钮, 系统字体
STYLE_SHEET = """
QMainWindow, QWidget {
    background-color: #f0f8f0;
    color: #1a3a1a;
    font-family: -apple-system, "SF Pro Text", "SF Pro", "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 10pt;
}

/* ---- Bento Cards (淡绿毛玻璃) ---- */
QGroupBox {
    background-color: rgba(245, 255, 245, 0.88);
    border: 1px solid rgba(52, 199, 89, 0.12);
    border-radius: 20px;
    margin-top: 18px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #1a3a1a;
    font-size: 11pt;
    font-weight: 700;
}

/* ---- Labels ---- */
QLabel { background: transparent; color: #1a3a1a; }
QLabel#dimLabel { color: #6b8f6b; font-size: 9pt; }
QLabel#titleLabel {
    color: #1a3a1a; font-size: 17pt; font-weight: 700;
    letter-spacing: -0.02em;
}
QLabel#connOk { color: #2da44e; font-size: 9pt; font-weight: 500; }
QLabel#connErr { color: #ff3b30; font-size: 9pt; font-weight: 500; }
QLabel#partialLabel {
    color: #6b8f6b; font-style: italic; font-size: 9pt;
    padding: 4px 0;
}
QLabel#offlineBadge {
    color: #2da44e; font-size: 8pt; font-weight: 700;
    border: 1px solid rgba(45, 164, 78, 0.3); border-radius: 8px;
    padding: 2px 10px;
    background: rgba(45, 164, 78, 0.08);
}
QLabel#listeningBadge {
    color: #ff9500; font-size: 8pt; font-weight: 700;
    border: 1px solid rgba(255, 149, 0, 0.3); border-radius: 8px;
    padding: 2px 10px;
    background: rgba(255, 149, 0, 0.08);
}
QLabel#vadLevel { color: #2da44e; font-size: 9pt; }

/* ---- Inputs (无边框, 浅绿背景) ---- */
QLineEdit, QTextEdit, QListWidget {
    background-color: #ebf5eb;
    color: #1a3a1a;
    border: 1.5px solid transparent;
    border-radius: 12px;
    padding: 8px 12px;
    selection-background-color: #34c759;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QListWidget:focus {
    background-color: #ffffff;
    border: 1.5px solid #34c759;
}
QListWidget {
    background-color: rgba(245, 255, 245, 0.7);
    border: 1px solid rgba(52, 199, 89, 0.08);
    border-radius: 12px;
}
QListWidget::item {
    border-radius: 8px;
    padding: 4px 8px;
}
QListWidget::item:hover { background: rgba(52, 199, 89, 0.06); }
QListWidget::item:selected {
    background: rgba(52, 199, 89, 0.12);
    color: #2da44e;
}

/* ---- Button Hierarchy ---- */
/* Secondary (默认) */
QPushButton {
    background-color: #d4e8d4;
    color: #1a3a1a;
    border: none;
    border-radius: 12px;
    padding: 7px 20px;
    font-weight: 600;
    font-size: 10pt;
}
QPushButton:hover { background-color: #c0dec0; }
QPushButton:pressed { background-color: #b0d4b0; }

/* Primary (发送) */
QPushButton#sendBtn {
    background-color: #2da44e;
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 10px 28px;
    font-size: 11pt;
    font-weight: 600;
}
QPushButton#sendBtn:hover { background-color: #2cb359; }
QPushButton#sendBtn:pressed { background-color: #269a45; }
QPushButton#sendBtn:disabled {
    background-color: #c0d4c0;
    color: #8fb58f;
}

/* Mic PTT */
QPushButton#micBtn {
    background-color: rgba(45, 164, 78, 0.12);
    color: #1a7a37;
    border: 1.5px solid rgba(45, 164, 78, 0.3);
    border-radius: 12px;
    padding: 8px 20px;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton#micBtn:hover {
    background-color: rgba(45, 164, 78, 0.2);
    border: 1.5px solid rgba(45, 164, 78, 0.5);
}
QPushButton#micBtn:pressed { background-color: rgba(45, 164, 78, 0.08); }
QPushButton#micBtn:disabled {
    color: #b0c8b0;
    border: 1.5px solid rgba(0, 0, 0, 0.06);
    background: rgba(0, 0, 0, 0.03);
}

/* Recording */
QPushButton#micRecording {
    background-color: #ff3b30;
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 8px 20px;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton#micRecording:hover { background-color: #ff453a; }
QPushButton#micRecording:pressed { background-color: #d70015; }

/* Continuous */
QPushButton#micContinuous {
    background-color: rgba(255, 149, 0, 0.12);
    color: #c93400;
    border: 1.5px solid rgba(255, 149, 0, 0.3);
    border-radius: 12px;
    padding: 8px 20px;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton#micContinuous:hover {
    background-color: rgba(255, 149, 0, 0.2);
    border: 1.5px solid rgba(255, 149, 0, 0.5);
}
QPushButton#micContinuous:pressed { background-color: rgba(255, 149, 0, 0.08); }

QPushButton#micContinuousActive {
    background-color: #ff9500;
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 8px 20px;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton#micContinuousActive:hover { background-color: #ffa00a; }
QPushButton#micContinuousActive:pressed { background-color: #e68600; }

/* ComboBox */
QComboBox {
    background-color: #ebf5eb;
    color: #1a3a1a;
    border: 1.5px solid transparent;
    border-radius: 10px;
    padding: 5px 10px;
    min-width: 70px;
}
QComboBox:hover { background-color: #dcecdc; }
QComboBox:focus { background-color: #ffffff; border: 1.5px solid #34c759; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow {
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #6b8f6b;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: rgba(245, 255, 245, 0.95);
    color: #1a3a1a;
    selection-background-color: #2da44e;
    selection-color: #ffffff;
    border: 1px solid rgba(52, 199, 89, 0.12);
    border-radius: 12px;
    outline: none;
    padding: 4px;
}
QComboBox QAbstractItemView::item {
    border-radius: 6px;
    padding: 4px 8px;
}

/* Checkbox */
QCheckBox { background: transparent; spacing: 8px; color: #1a3a1a; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1.5px solid #b0c8b0;
    background: #ebf5eb;
}
QCheckBox::indicator:hover { border: 1.5px solid #6b8f6b; }
QCheckBox::indicator:checked {
    background: #2da44e;
    border: 1.5px solid #2da44e;
}

/* Radio */
QRadioButton { background: transparent; spacing: 8px; color: #1a3a1a; }
QRadioButton::indicator {
    width: 16px; height: 16px;
    border-radius: 8px;
    border: 1.5px solid #b0c8b0;
    background: #ebf5eb;
}
QRadioButton::indicator:checked {
    background: #2da44e;
    border: 2px solid #ffffff;
}

/* Hotkey btn */
QPushButton#hotkeyBtn {
    background-color: #ebf5eb;
    color: #2da44e;
    border: 1.5px dashed rgba(45, 164, 78, 0.3);
    border-radius: 10px;
    padding: 4px 12px;
    font-weight: 600;
    min-width: 70px;
}
QPushButton#hotkeyBtn:hover {
    border: 1.5px dashed rgba(45, 164, 78, 0.6);
    background-color: rgba(45, 164, 78, 0.05);
}
QPushButton#hotkeyBtn:pressed {
    background-color: rgba(45, 164, 78, 0.1);
}

/* Settings btn */
QPushButton#settingsBtn {
    background-color: rgba(245, 255, 245, 0.7);
    color: #2da44e;
    border: 1px solid rgba(52, 199, 89, 0.1);
    border-radius: 12px;
    padding: 5px 16px;
    font-weight: 600;
}
QPushButton#settingsBtn:hover {
    background-color: rgba(45, 164, 78, 0.06);
    border: 1px solid rgba(45, 164, 78, 0.2);
}
QPushButton#settingsBtn:pressed { background-color: rgba(45, 164, 78, 0.1); }

/* Status bar */
QStatusBar {
    background-color: rgba(245, 255, 245, 0.7);
    color: #6b8f6b;
    border-top: 1px solid rgba(52, 199, 89, 0.08);
    font-size: 9pt;
}

/* Scroll */
QScrollArea { background-color: transparent; border: none; }
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    border-radius: 4px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: rgba(52, 199, 89, 0.2);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: rgba(52, 199, 89, 0.35); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }

/* Slider */
QSlider::groove:horizontal {
    background: #d4e8d4;
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #2da44e;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    width: 18px; height: 18px;
    border-radius: 9px;
    border: 1px solid rgba(52, 199, 89, 0.15);
    margin: -6px 0;
}
QSlider::handle:horizontal:hover {
    border: 2px solid #2da44e;
}

/* SpinBox */
QSpinBox {
    background-color: #ebf5eb;
    color: #1a3a1a;
    border: 1.5px solid transparent;
    border-radius: 8px;
    padding: 3px 6px;
}
QSpinBox:focus { background-color: #ffffff; border: 1.5px solid #34c759; }

/* Dialog */
QDialog { background-color: #f0f8f0; }
"""


# ============================================================
# 淡绿色极光背景 - 直接在主窗口 paintEvent 绘制
# ============================================================
def paint_aurora_background(widget, event):
    """在主窗口背景上绘制淡绿色弥散光球。"""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)

    w, h = widget.width(), widget.height()
    if w == 0 or h == 0:
        return

    # 底色: 淡绿白
    painter.fillRect(event.rect(), QColor(240, 248, 240))

    # 光球 1: 淡绿 - 左上
    c1 = QRadialGradient(w * 0.15, h * 0.15, max(w, h) * 0.5)
    c1.setColorAt(0, QColor(120, 200, 130, 80))
    c1.setColorAt(0.5, QColor(120, 200, 130, 30))
    c1.setColorAt(1, QColor(120, 200, 130, 0))
    painter.setBrush(QBrush(c1))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(w * 0.15, h * 0.15), w * 0.55, h * 0.55)

    # 光球 2: 淡青绿 - 右下
    c2 = QRadialGradient(w * 0.85, h * 0.8, max(w, h) * 0.5)
    c2.setColorAt(0, QColor(100, 220, 180, 60))
    c2.setColorAt(0.5, QColor(100, 220, 180, 20))
    c2.setColorAt(1, QColor(100, 220, 180, 0))
    painter.setBrush(QBrush(c2))
    painter.drawEllipse(QPointF(w * 0.85, h * 0.8), w * 0.5, h * 0.5)

    # 光球 3: 淡黄绿 - 中上
    c3 = QRadialGradient(w * 0.6, h * 0.3, max(w, h) * 0.35)
    c3.setColorAt(0, QColor(180, 220, 100, 40))
    c3.setColorAt(1, QColor(180, 220, 100, 0))
    painter.setBrush(QBrush(c3))
    painter.drawEllipse(QPointF(w * 0.6, h * 0.3), w * 0.35, h * 0.35)


class OSCSender:
    def __init__(self):
        self._client = None
        self._ip = DEFAULT_IP
        self._port = DEFAULT_PORT

    def connect(self, ip, port):
        self._ip = ip
        self._port = port
        self._client = udp_client.SimpleUDPClient(ip, port)

    def send_chatbox(self, text, send_immediately=True, notify=False):
        if self._client is None:
            self.connect(self._ip, self._port)
        try:
            self._client.send_message("/chatbox/input", [text, send_immediately, notify])
            return True
        except Exception:
            return False

    def send_typing(self, is_typing):
        if self._client is None:
            return
        try:
            self._client.send_message("/chatbox/typing", [is_typing])
        except Exception:
            pass


def list_microphones():
    mics = []
    try:
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                mics.append((i, info.get("name", f"设备 {i}")))
        pa.terminate()
    except Exception:
        pass
    return mics


# ============================================================
# 翻译引擎（百度官方 API + MyMemory 免费备用）
# ============================================================
TRANSLATE_LANGS = [
    ("英语", "en"),
    ("日语", "jp"),
    ("韩语", "kor"),
    ("法语", "fra"),
    ("德语", "de"),
    ("俄语", "ru"),
    ("西班牙语", "spa"),
    ("意大利语", "it"),
    ("葡萄牙语", "pt"),
    ("泰语", "th"),
    ("越南语", "vie"),
    ("阿拉伯语", "ara"),
]

# MyMemory 使用 ISO 639-1 两字母代码
_MYMEMORY_LANG_MAP = {
    "zh": "zh", "en": "en", "jp": "ja", "kor": "ko",
    "fra": "fr", "de": "de", "ru": "ru", "spa": "es",
    "it": "it", "pt": "pt", "th": "th", "vie": "vi", "ara": "ar",
}


class BaiduTranslator:
    """双模式翻译器：
    1. 百度官方 API（需 AppID + 密钥，免费注册: fanyi-api.baidu.com）
    2. MyMemory 免费 API（无需密钥，作为备用）
    """

    def __init__(self):
        self._baidu_appid = ""
        self._baidu_secret = ""

    def set_credentials(self, appid, secret):
        """设置百度 API 凭据。"""
        self._baidu_appid = appid or ""
        self._baidu_secret = secret or ""

    def has_baidu_api(self):
        """是否配置了百度官方 API。"""
        return bool(self._baidu_appid and self._baidu_secret)

    def translate(self, text, from_lang="zh", to_lang="en"):
        """翻译文本，返回 (译文, 错误信息)。成功时错误为 None。"""
        if not text.strip():
            return "", None
        # 优先使用百度官方 API
        if self.has_baidu_api():
            result, err = self._translate_baidu(text, from_lang, to_lang)
            if not err:
                return result, None
        # 备用：MyMemory 免费 API
        return self._translate_mymemory(text, from_lang, to_lang)

    def _translate_baidu(self, text, from_lang, to_lang):
        """百度官方 API（需要 AppID + 密钥）。"""
        try:
            salt = str(random.randint(32768, 65536))
            sign_str = self._baidu_appid + text + salt + self._baidu_secret
            sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
            params = urllib.parse.urlencode({
                "q": text,
                "from": from_lang,
                "to": to_lang,
                "appid": self._baidu_appid,
                "salt": salt,
                "sign": sign,
            })
            url = f"https://fanyi-api.baidu.com/api/trans/vip/translate?{params}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                trans_result = result.get("trans_result", [])
                if trans_result:
                    dst = "\n".join(
                        item.get("dst", "") for item in trans_result
                    )
                    return dst, None
                return "", result.get("error_msg", "百度API返回异常")
        except Exception as e:
            return "", f"百度API: {e}"

    def _translate_mymemory(self, text, from_lang, to_lang):
        """MyMemory 免费 API（无需密钥）。"""
        try:
            src = _MYMEMORY_LANG_MAP.get(from_lang, from_lang)
            tgt = _MYMEMORY_LANG_MAP.get(to_lang, to_lang)
            encoded = urllib.parse.quote(text)
            url = (
                f"https://api.mymemory.translated.net/get?"
                f"q={encoded}&langpair={src}|{tgt}"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("responseStatus") == 200:
                    translated = result.get("responseData", {}).get(
                        "translatedText", ""
                    )
                    if translated:
                        return translated, None
                return "", result.get("responseDetails", "MyMemory错误")
        except Exception as e:
            return "", f"MyMemory: {e}"

    def format_bilingual(self, original, translation, separator="\n"):
        """将原文和译文组合为双语显示。"""
        return f"{original}{separator}{translation}"


# ============================================================
# 设置对话框
# ============================================================
class SettingsDialog(QDialog):
    """应用设置对话框，可调整横竖屏、VAD参数等。"""

    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(420)
        self._cfg = dict(current_config)  # copy
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # ---- 布局设置 ----
        layout_group = QGroupBox("界面布局")
        layout_form = QFormLayout(layout_group)
        self.portrait_radio = QRadioButton("竖屏（单列）")
        self.portrait_radio.setToolTip("所有内容从上到下排列，适合窄窗口")
        self.landscape_radio = QRadioButton("横屏（双列）")
        self.landscape_radio.setToolTip("左侧放操作区，右侧放历史记录，适合宽屏幕")
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.portrait_radio)
        mode_row.addWidget(self.landscape_radio)
        mode_row.addStretch()
        layout_form.addRow("显示模式:", mode_row)
        if self._cfg.get("layout_mode", "portrait") == "landscape":
            self.landscape_radio.setChecked(True)
        else:
            self.portrait_radio.setChecked(True)

        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setMinimum(8)
        self.font_size_slider.setMaximum(16)
        self.font_size_slider.setValue(self._cfg.get("font_size", 10))
        self.font_size_label = QLabel(f"{self.font_size_slider.value()}pt")
        self.font_size_slider.valueChanged.connect(
            lambda v: self.font_size_label.setText(f"{v}pt")
        )
        font_row = QHBoxLayout()
        font_row.addWidget(self.font_size_slider)
        font_row.addWidget(self.font_size_label)
        layout_form.addRow("字体大小:", font_row)
        layout.addWidget(layout_group)

        # ---- VAD 参数 ----
        vad_group = QGroupBox("语音检测参数 (VAD)")
        vad_form = QFormLayout(vad_group)

        self.vad_threshold_slider = QSlider(Qt.Horizontal)
        self.vad_threshold_slider.setMinimum(10)
        self.vad_threshold_slider.setMaximum(90)
        self.vad_threshold_slider.setValue(int(self._cfg.get("vad_threshold", 0.5) * 100))
        self.vad_threshold_label = QLabel(f"{self.vad_threshold_slider.value() / 100:.2f}")
        self.vad_threshold_slider.valueChanged.connect(
            lambda v: self.vad_threshold_label.setText(f"{v / 100:.2f}")
        )
        vad_threshold_row = QHBoxLayout()
        vad_threshold_row.addWidget(self.vad_threshold_slider)
        vad_threshold_row.addWidget(self.vad_threshold_label)
        vad_form.addRow("灵敏度阈值:", vad_threshold_row)

        self.silence_dur_slider = QSlider(Qt.Horizontal)
        self.silence_dur_slider.setMinimum(200)
        self.silence_dur_slider.setMaximum(2000)
        self.silence_dur_slider.setValue(int(self._cfg.get("min_silence_duration", 0.5) * 1000))
        self.silence_dur_label = QLabel(f"{self.silence_dur_slider.value() / 1000:.1f}s")
        self.silence_dur_slider.valueChanged.connect(
            lambda v: self.silence_dur_label.setText(f"{v / 1000:.1f}s")
        )
        silence_row = QHBoxLayout()
        silence_row.addWidget(self.silence_dur_slider)
        silence_row.addWidget(self.silence_dur_label)
        vad_form.addRow("静音截断时长:", silence_row)

        self.min_speech_slider = QSlider(Qt.Horizontal)
        self.min_speech_slider.setMinimum(100)
        self.min_speech_slider.setMaximum(1000)
        self.min_speech_slider.setValue(int(self._cfg.get("min_speech_duration", 0.25) * 1000))
        self.min_speech_label = QLabel(f"{self.min_speech_slider.value() / 1000:.2f}s")
        self.min_speech_slider.valueChanged.connect(
            lambda v: self.min_speech_label.setText(f"{v / 1000:.2f}s")
        )
        min_speech_row = QHBoxLayout()
        min_speech_row.addWidget(self.min_speech_slider)
        min_speech_row.addWidget(self.min_speech_label)
        vad_form.addRow("最短语音时长:", min_speech_row)
        layout.addWidget(vad_group)

        # ---- OSC 参数 ----
        osc_group = QGroupBox("OSC 发送参数")
        osc_form = QFormLayout(osc_group)
        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setMinimum(16)
        self.max_chars_spin.setMaximum(500)
        self.max_chars_spin.setValue(self._cfg.get("max_chars", 144))
        osc_form.addRow("最大字符数:", self.max_chars_spin)
        layout.addWidget(osc_group)

        # ---- 翻译设置 ----
        trans_group = QGroupBox("翻译设置")
        trans_form = QFormLayout(trans_group)
        self.trans_enabled_chk = QCheckBox("启用翻译（发送前自动翻译为目标语言）")
        self.trans_enabled_chk.setChecked(self._cfg.get("translate_enabled", False))
        trans_form.addRow("", self.trans_enabled_chk)

        self.trans_lang_combo = QComboBox()
        for label, code in TRANSLATE_LANGS:
            self.trans_lang_combo.addItem(label, code)
        cur_target = self._cfg.get("translate_target", "en")
        for i in range(self.trans_lang_combo.count()):
            if self.trans_lang_combo.itemData(i) == cur_target:
                self.trans_lang_combo.setCurrentIndex(i)
                break
        trans_form.addRow("目标语言:", self.trans_lang_combo)

        self.trans_mode_combo = QComboBox()
        self.trans_mode_combo.addItem("双语显示（原文 + 译文）", "bilingual")
        self.trans_mode_combo.addItem("仅译文", "translated")
        cur_mode = self._cfg.get("translate_mode", "bilingual")
        for i in range(self.trans_mode_combo.count()):
            if self.trans_mode_combo.itemData(i) == cur_mode:
                self.trans_mode_combo.setCurrentIndex(i)
                break
        trans_form.addRow("显示方式:", self.trans_mode_combo)

        # 百度 API 凭据（可选，填写后使用百度官方 API；不填则用免费备用接口）
        self.baidu_appid_edit = QLineEdit()
        self.baidu_appid_edit.setPlaceholderText("可选，填写后使用百度官方 API")
        self.baidu_appid_edit.setText(self._cfg.get("baidu_appid", ""))
        trans_form.addRow("百度 AppID:", self.baidu_appid_edit)

        self.baidu_secret_edit = QLineEdit()
        self.baidu_secret_edit.setPlaceholderText("百度翻译 API 密钥")
        self.baidu_secret_edit.setEchoMode(QLineEdit.Password)
        self.baidu_secret_edit.setText(self._cfg.get("baidu_secret", ""))
        trans_form.addRow("百度密钥:", self.baidu_secret_edit)

        hint_label = QLabel(
            "提示：不填 AppID/密钥时会自动使用 MyMemory 免费翻译接口。\n"
            "百度 API 免费注册: fanyi-api.baidu.com"
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: #86868b; font-size: 9pt;")
        trans_form.addRow("", hint_label)
        layout.addWidget(trans_group)

        # ---- 按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("保存并应用")
        save_btn.setObjectName("sendBtn")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_save(self):
        self._cfg["layout_mode"] = "landscape" if self.landscape_radio.isChecked() else "portrait"
        self._cfg["font_size"] = self.font_size_slider.value()
        self._cfg["vad_threshold"] = self.vad_threshold_slider.value() / 100
        self._cfg["min_silence_duration"] = self.silence_dur_slider.value() / 1000
        self._cfg["min_speech_duration"] = self.min_speech_slider.value() / 1000
        self._cfg["max_chars"] = self.max_chars_spin.value()
        self._cfg["translate_enabled"] = self.trans_enabled_chk.isChecked()
        self._cfg["translate_target"] = self.trans_lang_combo.currentData() or "en"
        self._cfg["translate_mode"] = self.trans_mode_combo.currentData() or "bilingual"
        self._cfg["baidu_appid"] = self.baidu_appid_edit.text().strip()
        self._cfg["baidu_secret"] = self.baidu_secret_edit.text().strip()
        self.accept()

    def get_config(self):
        return self._cfg


class VoiceEngine(QObject):
    """
    sherpa-onnx SenseVoice + Silero VAD 语音引擎。
    支持两种模式：
    - PTT（按键录音）：手动开始/停止
    - 连续监听：VAD 自动检测语音端点，说完自动识别
    """
    partialResult = pyqtSignal(str)
    finalResult = pyqtSignal(str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    vadState = pyqtSignal(bool)  # True=正在说话, False=静音
    pttFinished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._recognizer = None
        self._vad = None
        self._pa = None
        self._stream = None
        self._running = False
        self._mode = None  # "ptt" or "continuous"
        self._stop_flag = False
        self._audio_queue = queue.Queue()
        self._ptt_buffer = []
        self._language = "zh"
        self._use_itn = True
        self._device_index = None
        # VAD 参数（可外部调整）
        self._vad_threshold = 0.5
        self._min_silence_duration = 0.5
        self._min_speech_duration = 0.25
        self._max_speech_duration = 30
        # 连续模式状态
        self._in_speech = False

    def set_vad_params(self, threshold=None, min_silence=None, min_speech=None, max_speech=None):
        """更新 VAD 参数（下次初始化模型时生效）。"""
        if threshold is not None:
            self._vad_threshold = threshold
        if min_silence is not None:
            self._min_silence_duration = min_silence
        if min_speech is not None:
            self._min_speech_duration = min_speech
        if max_speech is not None:
            self._max_speech_duration = max_speech

    def _init_models(self):
        if self._recognizer is not None:
            return
        if not os.path.exists(ASR_MODEL):
            raise FileNotFoundError(f"找不到语音识别模型: {ASR_MODEL}")
        if not os.path.exists(VAD_MODEL):
            raise FileNotFoundError(f"找不到 VAD 模型: {VAD_MODEL}")

        self.status.emit("正在加载语音模型...")
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=ASR_MODEL,
            tokens=ASR_TOKENS,
            num_threads=2,
            use_itn=True,
            language=self._language,
        )

        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = VAD_MODEL
        vad_config.silero_vad.threshold = self._vad_threshold
        vad_config.silero_vad.min_silence_duration = self._min_silence_duration
        vad_config.silero_vad.min_speech_duration = self._min_speech_duration
        vad_config.silero_vad.max_speech_duration = self._max_speech_duration
        vad_config.sample_rate = SAMPLE_RATE
        vad_config.num_threads = 1
        self._vad = sherpa_onnx.VoiceActivityDetector(
            vad_config, buffer_size_in_seconds=60
        )

    def start_ptt(self, device_index=None, language="zh"):
        if self._running:
            return
        self._mode = "ptt"
        self._device_index = device_index
        self._language = language
        self._ptt_buffer = []
        self._stop_flag = False
        self._running = True
        threading.Thread(target=self._ptt_worker, daemon=True).start()

    def start_continuous(self, device_index=None, language="zh"):
        if self._running:
            return
        self._mode = "continuous"
        self._device_index = device_index
        self._language = language
        self._stop_flag = False
        self._running = True
        self._in_speech = False
        threading.Thread(target=self._continuous_worker, daemon=True).start()

    def stop(self):
        self._stop_flag = True

    def _open_stream(self):
        self._pa = pyaudio.PyAudio()
        dev_idx = self._device_index
        if dev_idx is not None:
            try:
                info = self._pa.get_device_info_by_index(dev_idx)
                if info.get("maxInputChannels", 0) == 0:
                    dev_idx = None
            except Exception:
                dev_idx = None

        def callback(in_data, frame_count, time_info, status):
            self._audio_queue.put(in_data)
            return (None, pyaudio.paContinue)

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=dev_idx,
            frames_per_buffer=FRAMES_PER_BUFFER,
            stream_callback=callback,
        )
        self._stream.start_stream()

    def _close_stream(self):
        try:
            if self._stream:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        try:
            if self._pa:
                self._pa.terminate()
        except Exception:
            pass
        self._pa = None
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    # ----------------------------------------------------------
    # PTT 模式
    # ----------------------------------------------------------
    def _ptt_worker(self):
        try:
            self._init_models()
            self.status.emit("正在录音... 再次点击停止")
            self._open_stream()

            while not self._stop_flag:
                try:
                    data = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                self._ptt_buffer.append(data)

            # 停止后识别
            self.status.emit("正在识别...")
            audio_data = b"".join(self._ptt_buffer)
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            stream = self._recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            self._recognizer.decode_stream(stream)
            text = stream.result.text.strip()

            if text:
                self.finalResult.emit(text)
                self.status.emit(f"识别完成: {text}")
            else:
                self.status.emit("未识别到语音内容")

        except FileNotFoundError as e:
            self.error.emit(str(e))
        except OSError as e:
            self.error.emit(f"麦克风错误: {e}\n请检查麦克风是否连接。")
        except Exception as e:
            self.error.emit(f"语音识别出错: {e}")
        finally:
            self._close_stream()
            self._running = False
            self.pttFinished.emit()

    # ----------------------------------------------------------
    # 连续监听模式
    # ----------------------------------------------------------
    def _continuous_worker(self):
        try:
            self._init_models()
            self.status.emit("连续监听已开启，说话后自动识别发送")
            self._open_stream()

            while not self._stop_flag:
                try:
                    data = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                self._vad.accept_waveform(samples)

                # UI: 显示说话状态
                if self._vad.is_speech_detected():
                    if not self._in_speech:
                        self._in_speech = True
                        self.vadState.emit(True)
                else:
                    if self._in_speech:
                        self._in_speech = False
                        self.vadState.emit(False)

                # VAD 检测到完整语音段后会放入队列，直接取出识别
                while not self._vad.empty():
                    seg = self._vad.front
                    audio = np.array(seg.samples, dtype=np.float32)
                    self._vad.pop()
                    if len(audio) > SAMPLE_RATE * 0.15:  # 至少 0.15 秒
                        self._recognize_segment(audio)

            # 停止时 flush 剩余音频
            self._vad.flush()
            while not self._vad.empty():
                seg = self._vad.front
                audio = np.array(seg.samples, dtype=np.float32)
                self._vad.pop()
                if len(audio) > SAMPLE_RATE * 0.15:
                    self._recognize_segment(audio)

        except FileNotFoundError as e:
            self.error.emit(str(e))
        except OSError as e:
            self.error.emit(f"麦克风错误: {e}\n请检查麦克风是否连接。")
        except Exception as e:
            self.error.emit(f"语音识别出错: {e}")
        finally:
            self._close_stream()
            self._running = False
            self._in_speech = False
            self.vadState.emit(False)
            self.pttFinished.emit()

    def _recognize_segment(self, samples):
        """在后台线程中识别一段语音。"""
        def worker():
            try:
                stream = self._recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, samples)
                self._recognizer.decode_stream(stream)
                text = stream.result.text.strip()
                if text:
                    self.finalResult.emit(text)
                    self.status.emit(f"识别: {text}")
            except Exception as e:
                self.error.emit(f"识别出错: {e}")

        threading.Thread(target=worker, daemon=True).start()


class MainWindow(QMainWindow):
    sendFinished = pyqtSignal(bool, str)
    translateFinished = pyqtSignal(str, str, str)  # (original, translated, error)

    def __init__(self):
        super().__init__()
        self.osc = OSCSender()
        self.voice = VoiceEngine()
        self.translator = BaiduTranslator()
        self._history = []
        self._typing_timer = QTimer(self)
        self._typing_timer.setSingleShot(True)
        self._typing_timer.timeout.connect(lambda: self.osc.send_typing(False))
        self._is_ptt = False
        self._is_continuous = False
        self._record_base_text = ""
        self._hotkey_enabled = False
        self._hotkey_name = ""
        self._hotkey_scan_code = None
        self._capturing_hotkey = False
        self._hotkey_hooked = False
        self._hotkey_mode = "hold"  # "hold" = 按住说话, "toggle" = 按键切换
        self._hotkey_toggle_active = False  # toggle 模式下是否正在录音
        self._hotkey_key_down = False  # 防止按键自动重复触发
        # 布局和设置参数
        self._layout_mode = "portrait"  # "portrait" or "landscape"
        self._font_size = 10
        self._vad_threshold = 0.5
        self._min_silence_duration = 0.5
        self._min_speech_duration = 0.25
        self._max_chars = 144
        # 翻译参数
        self._translate_enabled = False
        self._translate_target = "en"
        self._translate_mode = "bilingual"  # "bilingual" = 双语, "translated" = 仅译文
        self._translate_from = "zh"  # 源语言（跟随语音识别语言）
        # 容器引用
        self._main_container = None
        self._left_panel = None
        self._right_panel = None
        self._scroll = None
        self._aurora = None

        self.sendFinished.connect(self._on_send_finished)
        self.translateFinished.connect(self._on_translate_finished)
        self._create_widgets()
        self._load_config()
        self._apply_layout()

        self.voice.partialResult.connect(self._on_partial)
        self.voice.finalResult.connect(self._on_final)
        self.voice.status.connect(self.status_bar.showMessage)
        self.voice.error.connect(self._on_voice_error)
        self.voice.vadState.connect(self._on_vad_state)
        self.voice.pttFinished.connect(self._on_ptt_finished)

        self._load_history()
        self._populate_mics()
        self._connect_osc()
        self._update_char_count()
        self._apply_font_size()
        self._apply_vad_params_to_engine()

    # ----------------------------------------------------------
    # 创建所有控件（不组装布局）
    # ----------------------------------------------------------
    def _create_widgets(self):
        self.setWindowTitle(f"{APP_TITLE}  v{APP_VERSION}")
        self.setMinimumSize(720, 600)

        # 设置窗口图标
        icon_path = os.path.join(RES_DIR, "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(APP_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 窗口标识 (不使用透明背景，避免文字溢出)
        self.setObjectName("mainWindow")

        # ---- 标题行 ----
        self.title_widget = QWidget()
        title_row = QHBoxLayout(self.title_widget)
        title_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("VRChat OSC 聊天框发送器")
        title.setObjectName("titleLabel")
        title_row.addWidget(title)
        title_row.addStretch()
        badge = QLabel("SenseVoice 离线识别")
        badge.setObjectName("offlineBadge")
        title_row.addWidget(badge)
        title_row.addSpacing(8)
        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._open_settings)
        title_row.addWidget(self.settings_btn)

        self.subtitle_label = QLabel("打字或语音说话，一键/自动发送到 VRChat 聊天框")
        self.subtitle_label.setObjectName("dimLabel")
        self.subtitle_label.setWordWrap(True)

        # ---- OSC 设置 ----
        self.conn_group = QGroupBox("OSC 连接设置")
        conn_layout = QVBoxLayout(self.conn_group)
        conn_layout.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel("服务器:"))
        self.ip_edit = QLineEdit(DEFAULT_IP)
        self.ip_edit.setMaximumWidth(160)
        row.addWidget(self.ip_edit)
        row.addSpacing(12)
        row.addWidget(QLabel("端口:"))
        self.port_edit = QLineEdit(str(DEFAULT_PORT))
        self.port_edit.setMaximumWidth(80)
        row.addWidget(self.port_edit)
        row.addStretch()
        self.reconnect_btn = QPushButton("重连")
        self.reconnect_btn.clicked.connect(self._connect_osc)
        row.addWidget(self.reconnect_btn)
        conn_layout.addLayout(row)
        self.conn_label = QLabel("")
        self.conn_label.setObjectName("connOk")
        conn_layout.addWidget(self.conn_label)

        # ---- 消息输入 ----
        self.msg_group = QGroupBox("消息内容")
        msg_layout = QVBoxLayout(self.msg_group)
        msg_layout.setSpacing(6)
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("输入消息，或使用下方语音输入...")
        self.text_input.setMinimumHeight(60)
        self.text_input.textChanged.connect(self._on_text_changed)
        msg_layout.addWidget(self.text_input)
        self.partial_label = QLabel("")
        self.partial_label.setObjectName("partialLabel")
        self.partial_label.setWordWrap(True)
        msg_layout.addWidget(self.partial_label)
        self.char_label = QLabel("0 / 144 字符")
        self.char_label.setObjectName("dimLabel")
        msg_layout.addWidget(self.char_label)
        opt_row = QHBoxLayout()
        self.immediate_chk = QCheckBox("立即发送")
        self.immediate_chk.setChecked(True)
        opt_row.addWidget(self.immediate_chk)
        self.notify_chk = QCheckBox("提示音")
        self.notify_chk.setChecked(False)
        opt_row.addWidget(self.notify_chk)
        opt_row.addStretch()
        msg_layout.addLayout(opt_row)

        # ---- 翻译设置行 ----
        trans_row = QHBoxLayout()
        self.translate_chk = QCheckBox("🌐 翻译")
        self.translate_chk.setToolTip("启用后，发送前将文字翻译为目标语言")
        self.translate_chk.stateChanged.connect(self._on_translate_toggle)
        trans_row.addWidget(self.translate_chk)
        trans_row.addSpacing(8)
        trans_row.addWidget(QLabel("目标:"))
        self.translate_lang_combo = QComboBox()
        for label, code in TRANSLATE_LANGS:
            self.translate_lang_combo.addItem(label, code)
        self.translate_lang_combo.setCurrentIndex(0)  # 默认英语
        self.translate_lang_combo.currentIndexChanged.connect(lambda: self._save_config())
        trans_row.addWidget(self.translate_lang_combo)
        trans_row.addSpacing(8)
        trans_row.addWidget(QLabel("显示:"))
        self.translate_mode_combo = QComboBox()
        self.translate_mode_combo.addItem("双语显示", "bilingual")
        self.translate_mode_combo.addItem("仅译文", "translated")
        self.translate_mode_combo.currentIndexChanged.connect(lambda: self._save_config())
        trans_row.addWidget(self.translate_mode_combo)
        trans_row.addStretch()
        msg_layout.addLayout(trans_row)

        # ---- 发送按钮 ----
        self.btn_widget = QWidget()
        btn_row = QHBoxLayout(self.btn_widget)
        btn_row.setContentsMargins(0, 0, 0, 0)
        self.send_btn = QPushButton("发 送  (Ctrl+Enter)")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.clicked.connect(self._send)
        btn_row.addWidget(self.send_btn)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_text)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()

        # ---- 语音输入 ----
        self.voice_group = QGroupBox("语音输入（SenseVoice 离线识别）")
        voice_layout = QVBoxLayout(self.voice_group)
        voice_layout.setSpacing(6)

        # 设置行
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("麦克风:"))
        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumWidth(120)
        settings_row.addWidget(self.mic_combo, stretch=1)
        settings_row.addSpacing(6)
        settings_row.addWidget(QLabel("语言:"))
        self.lang_combo = QComboBox()
        for label, code in LANGUAGES:
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(1)  # 默认中文
        settings_row.addWidget(self.lang_combo)
        voice_layout.addLayout(settings_row)

        # 自动发送单独一行
        auto_row = QHBoxLayout()
        self.auto_send_chk = QCheckBox("识别后自动发送")
        self.auto_send_chk.setChecked(True)
        self.auto_send_chk.setToolTip("识别完成后自动发送到 VRChat")
        auto_row.addWidget(self.auto_send_chk)
        auto_row.addStretch()
        voice_layout.addLayout(auto_row)

        # 全局热键设置 - 第一行：热键启用 + 按键设置
        hotkey_row = QHBoxLayout()
        self.hotkey_chk = QCheckBox("全局热键")
        self.hotkey_chk.setToolTip("启用后，在任何界面（包括 VRChat 游戏内）按设定按键即可语音输入")
        self.hotkey_chk.stateChanged.connect(self._on_hotkey_toggle)
        hotkey_row.addWidget(self.hotkey_chk)

        hotkey_row.addSpacing(8)
        hotkey_row.addWidget(QLabel("按键:"))
        self.hotkey_btn = QPushButton("未设置")
        self.hotkey_btn.setObjectName("hotkeyBtn")
        self.hotkey_btn.setCursor(Qt.PointingHandCursor)
        self.hotkey_btn.setMinimumWidth(70)
        self.hotkey_btn.setToolTip("点击后按下想要设置的按键（按 Esc 取消）")
        self.hotkey_btn.clicked.connect(self._capture_hotkey)
        hotkey_row.addWidget(self.hotkey_btn)

        self.hotkey_clear_btn = QPushButton("清除")
        self.hotkey_clear_btn.setMaximumWidth(50)
        self.hotkey_clear_btn.clicked.connect(self._clear_hotkey)
        hotkey_row.addWidget(self.hotkey_clear_btn)

        hotkey_row.addStretch()
        voice_layout.addLayout(hotkey_row)

        # 全局热键设置 - 第二行：模式选择
        hotkey_mode_row = QHBoxLayout()
        hotkey_mode_row.addSpacing(24)  # 缩进对齐
        mode_label = QLabel("触发模式:")
        mode_label.setObjectName("dimLabel")
        hotkey_mode_row.addWidget(mode_label)
        self.hotkey_mode_hold = QRadioButton("按住说话")
        self.hotkey_mode_hold.setChecked(True)
        self.hotkey_mode_hold.setToolTip("按住按键开始录音，松开自动识别")
        self.hotkey_mode_toggle = QRadioButton("按键切换")
        self.hotkey_mode_toggle.setToolTip("按一下开始录音，再按一下停止并识别")
        self._hotkey_mode_group = QButtonGroup(self)
        self._hotkey_mode_group.addButton(self.hotkey_mode_hold, 0)
        self._hotkey_mode_group.addButton(self.hotkey_mode_toggle, 1)
        self._hotkey_mode_group.buttonClicked.connect(self._on_hotkey_mode_changed)
        hotkey_mode_row.addWidget(self.hotkey_mode_hold)
        hotkey_mode_row.addWidget(self.hotkey_mode_toggle)

        hotkey_mode_row.addStretch()
        voice_layout.addLayout(hotkey_mode_row)

        # 按钮行
        voice_btn_row = QHBoxLayout()
        self.ptt_btn = QPushButton("🎤  按住说话")
        self.ptt_btn.setObjectName("micBtn")
        self.ptt_btn.setCursor(Qt.PointingHandCursor)
        self.ptt_btn.clicked.connect(self._toggle_ptt)
        voice_btn_row.addWidget(self.ptt_btn)

        self.continuous_btn = QPushButton("🔄  连续监听")
        self.continuous_btn.setObjectName("micContinuous")
        self.continuous_btn.setCursor(Qt.PointingHandCursor)
        self.continuous_btn.clicked.connect(self._toggle_continuous)
        voice_btn_row.addWidget(self.continuous_btn)

        voice_btn_row.addStretch()

        self.vad_label = QLabel("")
        self.vad_label.setObjectName("dimLabel")
        voice_btn_row.addWidget(self.vad_label, 1)
        voice_layout.addLayout(voice_btn_row)

        self.voice_hint = QLabel("点击「按住说话」手动录音，或「连续监听」自动检测语音端点")
        self.voice_hint.setObjectName("dimLabel")
        self.voice_hint.setWordWrap(True)
        voice_layout.addWidget(self.voice_hint)

        # ---- 历史记录 ----
        self.hist_group = QGroupBox("历史记录（双击重新填入）")
        hist_layout = QVBoxLayout(self.hist_group)
        hist_layout.setSpacing(6)
        hist_btn_row = QHBoxLayout()
        hist_btn_row.addStretch()
        self.clear_hist_btn = QPushButton("清空历史")
        self.clear_hist_btn.clicked.connect(self._clear_history)
        hist_btn_row.addWidget(self.clear_hist_btn)
        hist_layout.addLayout(hist_btn_row)
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(60)
        self.history_list.itemDoubleClicked.connect(self._on_history_double_click)
        hist_layout.addWidget(self.history_list)

        # ---- 状态栏 ----
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        self.text_input.installEventFilter(self)

    # ----------------------------------------------------------
    # 布局组装：根据模式切换横竖屏
    # ----------------------------------------------------------
    def _apply_layout(self):
        # 清除旧的中央部件
        if self._main_container is not None:
            old = self.takeCentralWidget()
            if old:
                old.deleteLater()
        self._main_container = None
        self._left_panel = None
        self._right_panel = None
        self._scroll = None

        if self._layout_mode == "landscape":
            self._build_landscape()
        else:
            self._build_portrait()

    def _build_portrait(self):
        """竖屏：Bento Grid 单列。"""
        self.resize(760, 860)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        central = QWidget()
        scroll.setWidget(central)
        self.setCentralWidget(scroll)
        self._scroll = scroll

        root = QVBoxLayout(central)
        root.setContentsMargins(24, 24, 24, 16)
        root.setSpacing(16)

        root.addWidget(self.title_widget)
        root.addWidget(self.subtitle_label)
        root.addWidget(self.conn_group)
        root.addWidget(self.msg_group, stretch=1)
        root.addWidget(self.btn_widget)
        root.addWidget(self.voice_group)
        root.addWidget(self.hist_group, stretch=1)

    def _build_landscape(self):
        """横屏：Bento Grid 双列。"""
        self.resize(1160, 740)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(0)

        # 左侧面板
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_widget = QWidget()
        left_scroll.setWidget(left_widget)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(24, 24, 8, 16)
        left_layout.setSpacing(16)

        left_layout.addWidget(self.title_widget)
        left_layout.addWidget(self.subtitle_label)
        left_layout.addWidget(self.conn_group)
        left_layout.addWidget(self.msg_group, stretch=1)
        left_layout.addWidget(self.btn_widget)
        left_layout.addWidget(self.voice_group)
        left_layout.addStretch()

        splitter.addWidget(left_scroll)

        # 右侧面板
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 24, 24, 16)
        right_layout.setSpacing(16)
        right_layout.addWidget(self.hist_group)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)  # 左 3
        splitter.setStretchFactor(1, 1)  # 右 1
        splitter.setSizes([860, 300])

        self.setCentralWidget(splitter)
        self._main_container = splitter

    def _apply_font_size(self):
        """根据设置调整全局字体大小。"""
        app = QApplication.instance()
        additional = f"""
        QMainWindow, QWidget {{
            font-size: {self._font_size}pt;
        }}
        QGroupBox {{ font-size: {self._font_size + 1}pt; }}
        QGroupBox::title {{ font-size: {self._font_size + 1}pt; }}
        QLabel#titleLabel {{ font-size: {self._font_size + 7}pt; }}
        QPushButton#sendBtn {{ font-size: {self._font_size + 1}pt; }}
        QPushButton#micBtn {{ font-size: {self._font_size}pt; }}
        QPushButton#micContinuous {{ font-size: {self._font_size}pt; }}
        """
        # 合并到主样式表
        app.setStyleSheet(STYLE_SHEET + additional)

    def _apply_vad_params_to_engine(self):
        self.voice.set_vad_params(
            threshold=self._vad_threshold,
            min_silence=self._min_silence_duration,
            min_speech=self._min_speech_duration,
        )

    def eventFilter(self, obj, event):
        if obj is self.text_input and event.type() == event.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and \
               event.modifiers() & Qt.ControlModifier:
                self._send()
                return True
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        """绘制淡绿色极光背景。"""
        paint_aurora_background(self, event)
        super().paintEvent(event)

    def resizeEvent(self, event):
        """窗口大小变化时重绘背景。"""
        super().resizeEvent(event)
        self.update()

    # ----------------------------------------------------------
    # 设置对话框
    # ----------------------------------------------------------
    def _open_settings(self):
        cfg = self._get_current_config()
        dlg = SettingsDialog(cfg, self)
        if dlg.exec_() == QDialog.Accepted:
            new_cfg = dlg.get_config()
            old_mode = self._layout_mode
            self._layout_mode = new_cfg.get("layout_mode", "portrait")
            self._font_size = new_cfg.get("font_size", 10)
            self._vad_threshold = new_cfg.get("vad_threshold", 0.5)
            self._min_silence_duration = new_cfg.get("min_silence_duration", 0.5)
            self._min_speech_duration = new_cfg.get("min_speech_duration", 0.25)
            self._max_chars = new_cfg.get("max_chars", 144)
            self._translate_enabled = new_cfg.get("translate_enabled", False)
            self._translate_target = new_cfg.get("translate_target", "en")
            self._translate_mode = new_cfg.get("translate_mode", "bilingual")
            self.translator.set_credentials(
                new_cfg.get("baidu_appid", ""),
                new_cfg.get("baidu_secret", ""),
            )

            # 同步到主界面控件
            self.translate_chk.setChecked(self._translate_enabled)
            for i in range(self.translate_lang_combo.count()):
                if self.translate_lang_combo.itemData(i) == self._translate_target:
                    self.translate_lang_combo.setCurrentIndex(i)
                    break
            for i in range(self.translate_mode_combo.count()):
                if self.translate_mode_combo.itemData(i) == self._translate_mode:
                    self.translate_mode_combo.setCurrentIndex(i)
                    break

            self._apply_font_size()
            self._apply_vad_params_to_engine()
            self._update_char_count()

            if old_mode != self._layout_mode:
                self._apply_layout()
            self._save_config()
            self.status_bar.showMessage("设置已保存并应用")

    def _get_current_config(self):
        return {
            "layout_mode": self._layout_mode,
            "font_size": self._font_size,
            "vad_threshold": self._vad_threshold,
            "min_silence_duration": self._min_silence_duration,
            "min_speech_duration": self._min_speech_duration,
            "max_chars": self._max_chars,
            "translate_enabled": self.translate_chk.isChecked(),
            "translate_target": self.translate_lang_combo.currentData() or "en",
            "translate_mode": self.translate_mode_combo.currentData() or "bilingual",
            "baidu_appid": self.translator._baidu_appid,
            "baidu_secret": self.translator._baidu_secret,
        }

    # ----------------------------------------------------------
    # OSC
    # ----------------------------------------------------------
    def _connect_osc(self):
        ip = self.ip_edit.text().strip()
        try:
            port = int(self.port_edit.text().strip())
        except ValueError:
            self.conn_label.setText("连接失败：端口必须是数字")
            self.conn_label.setObjectName("connErr")
            self._repolish(self.conn_label)
            return
        try:
            self.osc.connect(ip, port)
            self.conn_label.setText(f"已连接  {ip}:{port}")
            self.conn_label.setObjectName("connOk")
            self._repolish(self.conn_label)
            self.status_bar.showMessage(f"OSC 已就绪 → {ip}:{port}")
        except Exception as e:
            self.conn_label.setText(f"连接失败：{e}")
            self.conn_label.setObjectName("connErr")
            self._repolish(self.conn_label)

    def _repolish(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # ----------------------------------------------------------
    # 发送
    # ----------------------------------------------------------
    @staticmethod
    def _voice_lang_to_baidu(lang_code):
        """将语音识别语言代码映射为百度翻译语言代码。"""
        mapping = {
            "zh": "zh", "en": "en", "ja": "jp",
            "ko": "kor", "yue": "yue", "auto": "auto",
        }
        return mapping.get(lang_code, "auto")

    def _on_translate_toggle(self, state):
        """翻译开关变化时保存配置。"""
        self._translate_enabled = bool(state)
        self._save_config()

    def _get_send_text(self, text):
        """根据翻译设置，返回最终要发送的文本（同步，用于手动发送）。"""
        if not self._translate_enabled:
            return text, None

        from_lang = self._voice_lang_to_baidu(self._translate_from)
        translated, err = self.translator.translate(text, from_lang, self._translate_target)

        if err:
            return text, err  # 翻译失败时发送原文

        if self._translate_mode == "bilingual":
            send_text = self.translator.format_bilingual(text, translated)
        else:
            send_text = translated

        # 如果双语超长，回退为仅译文
        if len(send_text) > self._max_chars and self._translate_mode == "bilingual":
            send_text = translated

        return send_text, None

    def _send(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            self.status_bar.showMessage("消息为空")
            return

        # 从 UI 读取翻译设置
        self._translate_enabled = self.translate_chk.isChecked()
        self._translate_target = self.translate_lang_combo.currentData() or "en"
        self._translate_mode = self.translate_mode_combo.currentData() or "bilingual"
        self._translate_from = self.lang_combo.currentData() or "zh"

        if len(text) > self._max_chars:
            reply = QMessageBox.question(
                self, "超出字符限制",
                f"消息长度 {len(text)} 超过限制 {self._max_chars} 字符。\n仍然发送吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self.send_btn.setEnabled(False)

        if self._translate_enabled:
            self.status_bar.showMessage("正在翻译并发送…")
        else:
            self.status_bar.showMessage("正在发送…")
        immediate = self.immediate_chk.isChecked()
        notify = self.notify_chk.isChecked()

        def worker():
            send_text, err = self._get_send_text(text)
            if err:
                self.status_bar.showMessage(f"翻译失败，发送原文: {err}")
            ok = self.osc.send_chatbox(send_text, immediate, notify)
            self.sendFinished.emit(ok, send_text)

        threading.Thread(target=worker, daemon=True).start()

    def _on_send_finished(self, ok, text):
        self.send_btn.setEnabled(True)
        if ok:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self._add_history(f"[{ts}] {text}")
            self.text_input.clear()
            self.partial_label.setText("")
            self.status_bar.showMessage("发送成功")
        else:
            QMessageBox.critical(self, "发送失败", "无法发送 OSC 消息，请检查 IP 和端口。")

    def _on_translate_finished(self, original, translated, error):
        """翻译完成回调（预留给异步翻译结果显示）。"""
        if error:
            self.status_bar.showMessage(f"翻译失败: {error}")
        else:
            self.partial_label.setText(f"译文: {translated}")

    def _on_text_changed(self):
        self._update_char_count()
        self.osc.send_typing(True)
        self._typing_timer.start(1500)

    def _update_char_count(self):
        length = len(self.text_input.toPlainText())
        limit = self._max_chars
        color = "#ff3b30" if length > limit else ("#ff9500" if length > limit * 0.8 else "#6b8f6b")
        self.char_label.setText(f"{length} / {limit} 字符")
        self.char_label.setStyleSheet(f"color: {color};")

    def _clear_text(self):
        self.text_input.clear()
        self.partial_label.setText("")

    # ----------------------------------------------------------
    # 麦克风
    # ----------------------------------------------------------
    def _populate_mics(self):
        self.mic_combo.clear()
        mics = list_microphones()
        if not mics:
            self.mic_combo.addItem("未检测到麦克风", None)
            self.ptt_btn.setEnabled(False)
            self.continuous_btn.setEnabled(False)
            return
        for idx, name in mics:
            self.mic_combo.addItem(name[:45] + "..." if len(name) > 45 else name, idx)

    def _toggle_ptt(self):
        if self._is_continuous:
            return  # 连续模式运行中不可用
        if not self._is_ptt:
            self._start_ptt()
        else:
            self._stop_ptt()

    def _start_ptt(self):
        self._is_ptt = True
        self._record_base_text = self.text_input.toPlainText().strip()
        self.ptt_btn.setText("⏹  停止识别")
        self.ptt_btn.setObjectName("micRecording")
        self._repolish(self.ptt_btn)
        self.continuous_btn.setEnabled(False)
        self.mic_combo.setEnabled(False)
        self.lang_combo.setEnabled(False)
        self.voice_hint.setText("正在录音... 再次点击停止并识别")
        self.voice.start_ptt(
            device_index=self.mic_combo.currentData(),
            language=self.lang_combo.currentData() or "zh"
        )

    def _stop_ptt(self):
        self.voice.stop()
        self.ptt_btn.setEnabled(False)
        self.voice_hint.setText("正在识别...")

    def _toggle_continuous(self):
        if self._is_ptt:
            return
        if not self._is_continuous:
            self._start_continuous()
        else:
            self._stop_continuous()

    def _start_continuous(self):
        self._is_continuous = True
        self._record_base_text = ""
        self.continuous_btn.setText("⏹  停止监听")
        self.continuous_btn.setObjectName("micContinuousActive")
        self._repolish(self.continuous_btn)
        self.ptt_btn.setEnabled(False)
        self.mic_combo.setEnabled(False)
        self.lang_combo.setEnabled(False)
        self.voice_hint.setText("连续监听中，说话后会自动识别")
        self.voice.start_continuous(
            device_index=self.mic_combo.currentData(),
            language=self.lang_combo.currentData() or "zh"
        )

    def _stop_continuous(self):
        self.voice.stop()
        self.continuous_btn.setEnabled(False)
        self.voice_hint.setText("正在停止...")

    # ----------------------------------------------------------
    # 语音回调
    # ----------------------------------------------------------
    def _on_partial(self, text):
        self.partial_label.setText(f"识别中: {text}")

    def _on_final(self, text):
        if self._is_continuous:
            # 连续模式：直接发送或填入
            if self.auto_send_chk.isChecked():
                # 自动发送
                self.text_input.setPlainText(text)
                QTimer.singleShot(100, self._send)
            else:
                self.text_input.setPlainText(text)
                self._update_char_count()
        else:
            # PTT 模式：追加到输入框
            if self._record_base_text:
                combined = f"{self._record_base_text} {text}"
            else:
                combined = text
            self.text_input.setPlainText(combined)
            self.text_input.moveCursor(self.text_input.textCursor().End)
            self._update_char_count()
            if self.auto_send_chk.isChecked():
                QTimer.singleShot(200, self._send)

    def _on_vad_state(self, is_speaking):
        if is_speaking:
            self.vad_label.setText("🔊 检测到语音...")
            self.vad_label.setStyleSheet("color: #ff9500;")
        else:
            self.vad_label.setText("")

    def _on_voice_error(self, msg):
        self.partial_label.setText("")
        self.vad_label.setText("")
        QMessageBox.warning(self, "语音识别错误", msg)

    def _on_ptt_finished(self):
        was_ptt = self._is_ptt
        was_continuous = self._is_continuous
        self._is_ptt = False
        self._is_continuous = False
        self._hotkey_toggle_active = False
        self._update_hotkey_btn_visual(False)

        self.ptt_btn.setText("🎤  按住说话")
        self.ptt_btn.setObjectName("micBtn")
        self._repolish(self.ptt_btn)
        self.ptt_btn.setEnabled(True)

        self.continuous_btn.setText("🔄  连续监听")
        self.continuous_btn.setObjectName("micContinuous")
        self._repolish(self.continuous_btn)
        self.continuous_btn.setEnabled(True)

        self.mic_combo.setEnabled(True)
        self.lang_combo.setEnabled(True)
        self.vad_label.setText("")

        if was_ptt:
            self.voice_hint.setText("点击「按住说话」手动录音，或「连续监听」自动检测语音端点")
        elif was_continuous:
            self.voice_hint.setText("连续监听已停止")

    # ----------------------------------------------------------
    # 全局热键
    # ----------------------------------------------------------
    def _on_hotkey_toggle(self, state):
        enabled = bool(state)
        self._hotkey_enabled = enabled
        if enabled:
            if not self._hotkey_name:
                QMessageBox.information(
                    self, "提示", "请先点击「按键」按钮设置一个热键。"
                )
                self.hotkey_chk.setChecked(False)
                self._hotkey_enabled = False
                return
            self._start_hotkey_hook()
            mode_text = "按住" if self._hotkey_mode == "hold" else "切换"
            self.status_bar.showMessage(
                f"全局热键已启用 [{self._format_key_name(self._hotkey_name)}]（{mode_text}模式）"
            )
        else:
            self._stop_hotkey_hook()
            self._hotkey_toggle_active = False
            self._update_hotkey_btn_visual(False)
            self.status_bar.showMessage("全局热键已关闭")

    def _on_hotkey_mode_changed(self, btn):
        if btn is self.hotkey_mode_hold:
            self._hotkey_mode = "hold"
        else:
            self._hotkey_mode = "toggle"
        # 如果正在 toggle 录音，切模式时停止
        if self._hotkey_toggle_active and self._is_ptt:
            self._stop_ptt()
        self._hotkey_toggle_active = False
        self._update_hotkey_btn_visual(False)
        self._save_config()

    def _capture_hotkey(self):
        """进入按键捕获模式，等待用户按下任意键。"""
        if self._capturing_hotkey:
            return
        self._capturing_hotkey = True
        self.hotkey_btn.setText("按下任意键...")
        self.hotkey_btn.setStyleSheet("border-color: rgba(255,149,0,0.6); color: #ff9500;")

        # 先取消旧的 hook
        self._stop_hotkey_hook()

        def on_key(event):
            if not self._capturing_hotkey:
                return
            # Esc 取消捕获
            if event.name in ("esc", "escape"):
                self._capturing_hotkey = False
                QTimer.singleShot(0, self._cancel_capture_hotkey)
                return False
            # 忽略纯修饰键的按下事件（避免单独按 Ctrl/Shift/Alt 被设为热键）
            if event.name in ("left shift", "right shift", "left ctrl", "right ctrl",
                              "left alt", "right alt", "left windows", "right windows"):
                return
            self._capturing_hotkey = False
            self._hotkey_name = event.name
            self._hotkey_scan_code = event.scan_code
            # 在主线程更新 UI
            QTimer.singleShot(0, self._finish_capture_hotkey)
            return False  # 拦截这个按键

        keyboard.hook(on_key, suppress=False)

    def _cancel_capture_hotkey(self):
        """取消热键捕获。"""
        keyboard.unhook_all()
        self.hotkey_btn.setText(self._format_key_name(self._hotkey_name) if self._hotkey_name else "未设置")
        self.hotkey_btn.setStyleSheet("")
        if self._hotkey_enabled and self._hotkey_scan_code:
            self._start_hotkey_hook()
        self.status_bar.showMessage("已取消热键设置")

    def _finish_capture_hotkey(self):
        keyboard.unhook_all()
        display = self._format_key_name(self._hotkey_name)
        self.hotkey_btn.setText(display)
        self.hotkey_btn.setStyleSheet("")
        # 如果热键已启用，重新 hook
        if self._hotkey_enabled and self.hotkey_chk.isChecked():
            self._start_hotkey_hook()
        self.status_bar.showMessage(f"热键已设置为: {display}")

    def _clear_hotkey(self):
        self._stop_hotkey_hook()
        self._hotkey_name = ""
        self._hotkey_scan_code = None
        self._hotkey_enabled = False
        self.hotkey_chk.setChecked(False)
        self.hotkey_btn.setText("未设置")
        self.hotkey_btn.setStyleSheet("")
        self.status_bar.showMessage("热键已清除")

    def _format_key_name(self, name):
        """格式化按键名称用于显示。"""
        if not name:
            return "未设置"
        # 常见按键的中文名
        name_map = {
            "space": "空格", "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt",
            "caps lock": "CapsLock", "tab": "Tab", "enter": "回车",
            "backspace": "退格", "delete": "Delete", "insert": "Insert",
            "home": "Home", "end": "End", "page up": "PageUp", "page down": "PageDown",
            "up": "↑", "down": "↓", "left": "←", "right": "→",
            "esc": "Esc", "escape": "Esc",
            "left ctrl": "左Ctrl", "right ctrl": "右Ctrl",
            "left shift": "左Shift", "right shift": "右Shift",
            "left alt": "左Alt", "right alt": "右Alt",
            "left windows": "左Win", "right windows": "右Win",
            "num lock": "NumLock", "scroll lock": "ScrollLock",
            "print screen": "PrtSc", "pause": "Pause",
            "menu": "Menu",
        }
        return name_map.get(name.lower(), name.upper() if len(name) == 1 else name)

    def _start_hotkey_hook(self):
        if self._hotkey_hooked or not self._hotkey_scan_code:
            return
        try:
            keyboard.on_press_key(self._hotkey_scan_code, self._on_hotkey_press, suppress=False)
            keyboard.on_release_key(self._hotkey_scan_code, self._on_hotkey_release, suppress=False)
            self._hotkey_hooked = True
        except Exception as e:
            self._hotkey_hooked = False
            QMessageBox.warning(self, "热键错误", f"无法注册热键: {e}")

    def _stop_hotkey_hook(self):
        if self._hotkey_hooked:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
            self._hotkey_hooked = False
        # 如果正在 PTT，停止
        if self._is_ptt:
            self.voice.stop()

    def _on_hotkey_press(self, event):
        """热键按下：根据模式开始录音或切换状态。"""
        if self._is_continuous:
            return
        # 防止按键自动重复触发
        if self._hotkey_key_down:
            return
        self._hotkey_key_down = True

        if self._hotkey_mode == "hold":
            # 按住模式：按下开始录音
            if not self._is_ptt:
                self._update_hotkey_btn_visual(True)
                QTimer.singleShot(0, self._start_ptt)
        else:
            # 切换模式：按一下开始，再按一下停止
            if not self._is_ptt:
                self._hotkey_toggle_active = True
                self._update_hotkey_btn_visual(True)
                QTimer.singleShot(0, self._start_ptt)
            elif self._hotkey_toggle_active:
                self._hotkey_toggle_active = False
                self._update_hotkey_btn_visual(False)
                QTimer.singleShot(0, self._stop_ptt)

    def _on_hotkey_release(self, event):
        """热键松开：按住模式下停止录音。"""
        self._hotkey_key_down = False
        if self._hotkey_mode == "hold" and self._is_ptt:
            QTimer.singleShot(0, self._stop_ptt)

    def _update_hotkey_btn_visual(self, active):
        """热键录音时给按键按钮一个视觉提示。"""
        if active:
            self.hotkey_btn.setStyleSheet(
                "background-color: #ff3b30; color: #ffffff; border: 1px solid #ff3b30; font-weight: 600;"
            )
        else:
            self.hotkey_btn.setStyleSheet("")

    # ----------------------------------------------------------
    # 历史
    # ----------------------------------------------------------
    def _add_history(self, entry):
        self._history.insert(0, entry)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[:MAX_HISTORY]
        self.history_list.insertItem(0, entry)
        self._save_history()

    def _on_history_double_click(self, item):
        text = item.text()
        if "] " in text:
            text = text.split("] ", 1)[1]
        self.text_input.setPlainText(text)

    def _clear_history(self):
        if self._history:
            reply = QMessageBox.question(
                self, "确认", "确定要清空所有历史记录吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._history.clear()
                self.history_list.clear()
                self._save_history()

    def _load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self._history = json.load(f)
                for item in self._history:
                    self.history_list.addItem(item)
        except Exception:
            self._history = []

    def _save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ----------------------------------------------------------
    # 配置
    # ----------------------------------------------------------
    def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.ip_edit.setText(cfg.get("ip", DEFAULT_IP))
                self.port_edit.setText(str(cfg.get("port", DEFAULT_PORT)))
                self.immediate_chk.setChecked(cfg.get("immediate", True))
                self.notify_chk.setChecked(cfg.get("notify", False))
                self.auto_send_chk.setChecked(cfg.get("auto_send", True))
                lang = cfg.get("voice_lang", "zh")
                for i in range(self.lang_combo.count()):
                    if self.lang_combo.itemData(i) == lang:
                        self.lang_combo.setCurrentIndex(i)
                        break
                mic_idx = cfg.get("mic_index", -1)
                if mic_idx >= 0:
                    for i in range(self.mic_combo.count()):
                        if self.mic_combo.itemData(i) == mic_idx:
                            self.mic_combo.setCurrentIndex(i)
                            break
                # 加载热键设置
                self._hotkey_name = cfg.get("hotkey_name", "")
                self._hotkey_scan_code = cfg.get("hotkey_scan_code", None)
                self._hotkey_mode = cfg.get("hotkey_mode", "hold")
                if self._hotkey_name:
                    self.hotkey_btn.setText(self._format_key_name(self._hotkey_name))
                if self._hotkey_mode == "toggle":
                    self.hotkey_mode_toggle.setChecked(True)
                else:
                    self.hotkey_mode_hold.setChecked(True)
                if cfg.get("hotkey_enabled", False) and self._hotkey_scan_code:
                    self.hotkey_chk.setChecked(True)
                # 加载布局和参数设置
                self._layout_mode = cfg.get("layout_mode", "portrait")
                self._font_size = cfg.get("font_size", 10)
                self._vad_threshold = cfg.get("vad_threshold", 0.5)
                self._min_silence_duration = cfg.get("min_silence_duration", 0.5)
                self._min_speech_duration = cfg.get("min_speech_duration", 0.25)
                self._max_chars = cfg.get("max_chars", 144)
                # 翻译设置
                self._translate_enabled = cfg.get("translate_enabled", False)
                self._translate_target = cfg.get("translate_target", "en")
                self._translate_mode = cfg.get("translate_mode", "bilingual")
                self.translator.set_credentials(
                    cfg.get("baidu_appid", ""),
                    cfg.get("baidu_secret", ""),
                )
                self.translate_chk.setChecked(self._translate_enabled)
                for i in range(self.translate_lang_combo.count()):
                    if self.translate_lang_combo.itemData(i) == self._translate_target:
                        self.translate_lang_combo.setCurrentIndex(i)
                        break
                for i in range(self.translate_mode_combo.count()):
                    if self.translate_mode_combo.itemData(i) == self._translate_mode:
                        self.translate_mode_combo.setCurrentIndex(i)
                        break
        except Exception:
            pass

    def _save_config(self):
        try:
            cfg = {
                "ip": self.ip_edit.text().strip(),
                "port": int(self.port_edit.text().strip()),
                "immediate": self.immediate_chk.isChecked(),
                "notify": self.notify_chk.isChecked(),
                "auto_send": self.auto_send_chk.isChecked(),
                "voice_lang": self.lang_combo.currentData() or "zh",
                "mic_index": self.mic_combo.currentData() if self.mic_combo.currentData() is not None else -1,
                "hotkey_enabled": self.hotkey_chk.isChecked(),
                "hotkey_name": self._hotkey_name,
                "hotkey_scan_code": self._hotkey_scan_code,
                "hotkey_mode": self._hotkey_mode,
                "layout_mode": self._layout_mode,
                "font_size": self._font_size,
                "vad_threshold": self._vad_threshold,
                "min_silence_duration": self._min_silence_duration,
                "min_speech_duration": self._min_speech_duration,
                "max_chars": self._max_chars,
                "translate_enabled": self.translate_chk.isChecked(),
                "translate_target": self.translate_lang_combo.currentData() or "en",
                "translate_mode": self.translate_mode_combo.currentData() or "bilingual",
                "baidu_appid": self.translator._baidu_appid,
                "baidu_secret": self.translator._baidu_secret,
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def closeEvent(self, event):
        if self._is_ptt or self._is_continuous:
            self.voice.stop()
        self._stop_hotkey_hook()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self._save_config()
        self._save_history()
        self.osc.send_typing(False)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
