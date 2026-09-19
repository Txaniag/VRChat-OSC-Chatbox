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
import re
import math
import time
import ctypes
import tempfile
import subprocess
import base64
import webbrowser
import winreg
from colorsys import rgb_to_hls, hls_to_rgb
from collections import deque
import datetime
import threading
import queue
import hashlib
import random
import urllib.request
import urllib.parse
import socket

import numpy as np
import pyaudio
import sherpa_onnx
import keyboard
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QCheckBox, QListWidget,
    QListWidgetItem, QListView, QAbstractItemView, QGroupBox, QStatusBar,
    QMessageBox, QComboBox, QRadioButton, QButtonGroup, QScrollArea, QFrame,
    QDialog, QSlider, QSpinBox, QFormLayout, QDialogButtonBox, QSplitter,
    QGraphicsBlurEffect, QGraphicsOpacityEffect, QGraphicsDropShadowEffect,
    QStyledItemDelegate, QScrollBar, QSystemTrayIcon, QMenu
)
from PyQt5.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QPointF, QPoint, QRect, QRectF, QSize,
    QEvent,
    QPropertyAnimation, QParallelAnimationGroup, QVariantAnimation, QEasingCurve
)
from PyQt5.QtGui import (
    QIcon, QPainter, QRadialGradient, QColor, QBrush, QLinearGradient,
    QPixmap, QPen, QCursor
)
from pythonosc import udp_client
from pythonosc.osc_message_builder import OscMessageBuilder

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
DENOISER_MODEL = os.path.join(MODEL_DIR, "gtcrn_simple.onnx")

# ============================================================
# 常量
# ============================================================
APP_TITLE = "VRChat OSC Chatbox Sender"
APP_VERSION = "4.3.3"
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
# 注意: 基础 QWidget 背景必须透明, 否则会盖住主窗口 paintEvent 画的极光
_STYLE_SHEET_TEMPLATE = """
QMainWindow {
    background-color: #f0f8f0;
    color: #1a3a1a;
    font-family: -apple-system, "SF Pro Text", "SF Pro", "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 10pt;
}
QWidget {
    background: transparent;
    color: #1a3a1a;
    font-family: -apple-system, "SF Pro Text", "SF Pro", "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 10pt;
}
QSplitter { background: transparent; }
QSplitter::handle { background: transparent; }

/* ---- Bento Cards (淡绿毛玻璃) ---- */
QGroupBox {
    background-color: rgba(245, 255, 245, 0.88);
    border: 1px solid rgba(52, 199, 89, 0.12);
    border-radius: 20px;
    margin-top: 6px;
    padding: 42px 14px 14px 14px;
    font-weight: 600;
}
/* 标题放卡片内部左上角：原来 subcontrol-origin: margin + 固定 18px margin-top
   在不同字号/DPI 下标题会整行飘到卡片外，改为内部标题彻底规避 */
QGroupBox::title {
    subcontrol-origin: border;
    subcontrol-position: top left;
    left: 14px;
    top: 14px;
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
QLineEdit:disabled, QTextEdit:disabled {
    background-color: #e4eee4;
    color: #93ab93;
    border: 1.5px solid transparent;
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
QPushButton:disabled {
    background-color: #dcecdc;
    color: #9db89d;
}

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
QPushButton#micContinuous:disabled {
    color: #d4bb9a;
    border: 1.5px solid rgba(0, 0, 0, 0.06);
    background: rgba(0, 0, 0, 0.03);
}

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
QComboBox:disabled { background-color: #e4eee4; color: #93ab93; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow {
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #6b8f6b;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: rgba(245, 255, 245, 0.98);
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
    min-height: 22px;
}

/* Checkbox */
QCheckBox { background: transparent; spacing: 8px; color: #1a3a1a; }
QCheckBox:disabled { color: #9db89d; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border-radius: 5px;
    border: 1.5px solid #b0c8b0;
    background: #ebf5eb;
}
QCheckBox::indicator:hover { border: 1.5px solid #6b8f6b; }
QCheckBox::indicator:checked {
    background-color: #2da44e;
    border: 1.5px solid #2da44e;
    image: url(__CHECK_URL__);
}
QCheckBox::indicator:disabled {
    border: 1.5px solid #d4e4d4;
    background: #e4eee4;
}

/* Radio */
QRadioButton { background: transparent; spacing: 8px; color: #1a3a1a; }
QRadioButton::indicator {
    width: 17px; height: 17px;
    border-radius: 9px;
    border: 1.5px solid #b0c8b0;
    background: #ebf5eb;
}
QRadioButton::indicator:hover { border: 1.5px solid #6b8f6b; }
QRadioButton::indicator:checked {
    background: #ffffff;
    border: 5px solid #2da44e;
}
QRadioButton::indicator:disabled {
    border: 1.5px solid #d4e4d4;
    background: #e4eee4;
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
QStatusBar::item { border: none; }

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
QScrollBar::handle:vertical:pressed { background: rgba(52, 199, 89, 0.5); }
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
QSpinBox:disabled { background-color: #e4eee4; color: #93ab93; }

/* ---- 悬浮翻译按钮 ---- */
QPushButton#speakerBtn {
    background-color: rgba(53, 132, 228, 0.12);
    color: #1c6ba0;
    border: 1.5px solid rgba(53, 132, 228, 0.35);
    border-radius: 12px;
    padding: 8px 16px;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton#speakerBtn:hover {
    background-color: rgba(53, 132, 228, 0.2);
    border: 1.5px solid rgba(53, 132, 228, 0.55);
}
QPushButton#speakerBtn:pressed { background-color: rgba(53, 132, 228, 0.08); }
QPushButton#speakerBtn:disabled {
    color: #9db4c8;
    border: 1.5px solid rgba(0, 0, 0, 0.06);
    background: rgba(0, 0, 0, 0.03);
}
QPushButton#speakerBtnActive {
    background-color: #3574e4;
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 8px 16px;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton#speakerBtnActive:hover { background-color: #4a83e8; }
QPushButton#speakerBtnActive:pressed { background-color: #2c66c9; }

/* ---- 悬浮翻译窗 (深色玻璃) ---- */
QFrame#floatCard {
    background-color: rgba(26, 36, 28, 238);
    border: 1px solid rgba(126, 231, 135, 0.3);
    border-radius: 16px;
}
QLabel#floatTitle {
    color: #9fd8ac;
    font-size: 10pt;
    font-weight: 700;
    background: transparent;
}
QLabel#floatStatus {
    color: #8fae95;
    font-size: 8pt;
    background: transparent;
}
QPushButton#floatBtn {
    background: rgba(255, 255, 255, 0.08);
    color: #cfe8d4;
    border: none;
    border-radius: 8px;
    font-family: "Segoe UI Symbol";
    font-size: 9pt;
    padding: 0;
}
QPushButton#floatBtn:hover { background-color: rgba(255, 115, 99, 0.85); color: #ffffff; }
QComboBox#floatCombo {
    background-color: rgba(255, 255, 255, 0.09);
    color: #e8f5ea;
    border: 1px solid rgba(126, 231, 135, 0.25);
    border-radius: 8px;
    padding: 2px 6px;
    min-width: 56px;
    font-size: 8pt;
}
QComboBox#floatCombo:hover { background-color: rgba(255, 255, 255, 0.15); }
QComboBox#floatCombo::drop-down { border: none; width: 16px; }
QComboBox#floatCombo::down-arrow {
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #9fd8ac;
    margin-right: 4px;
}
QTextEdit#floatBody {
    background-color: transparent;
    color: #eef7ef;
    border: none;
    font-size: 9pt;
    selection-background-color: #2da44e;
    selection-color: #ffffff;
}

/* ---- 标题栏 macOS 红绿灯按钮：常显彩色圆点，悬停时符号淡入 ---- */
QLabel#winTitle {
    color: #527052;
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 0.01em;
}
QPushButton#tlMin, QPushButton#tlMax, QPushButton#tlClose {
    background-color: #cfd8cf;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 8px;
    color: transparent;
    font-family: "Segoe UI Symbol";
    font-size: 7pt;
    padding: 0;
}
QPushButton#tlMin { background-color: #febc2e; }
QPushButton#tlMax { background-color: #28c840; }
QPushButton#tlClose { background-color: #ff5f57; }
QPushButton#tlMin:hover { background-color: #ffcd4a; color: rgba(96, 64, 0, 0.65); }
QPushButton#tlMax:hover { background-color: #43d95c; color: rgba(0, 70, 15, 0.6); }
QPushButton#tlClose:hover { background-color: #ff7b74; color: rgba(96, 15, 8, 0.65); }
QPushButton#tlMin:pressed { background-color: #e5a523; }
QPushButton#tlMax:pressed { background-color: #1fa834; }
QPushButton#tlClose:pressed { background-color: #e04b43; }

/* Tooltip (Apple 深色胶囊) */
QToolTip {
    background-color: rgba(28, 44, 28, 0.92);
    color: #f5fff5;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 9pt;
}

/* Dialog */
QDialog { background-color: #f0f8f0; }
"""


# 下拉弹层视图专用样式：挂视图自身，保证透明容器下圆角/选中样式稳定
POPUP_VIEW_QSS = """
QListView {
    background-color: rgba(248, 253, 248, 0.99);
    color: #1a3a1a;
    border: 1px solid rgba(52, 199, 89, 0.28);
    border-radius: 12px;
    outline: none;
    padding: 6px;
    selection-background-color: #2da44e;
    selection-color: #ffffff;
}
QListView::item {
    border-radius: 8px;
    padding: 5px 10px;
    margin: 1px 2px;
    min-height: 22px;
    background: transparent;
}
QListView::item:hover { background: rgba(52, 199, 89, 0.15); }
QListView::item:selected { background: #2da44e; color: #ffffff; }
"""


def _ensure_check_png():
    """生成白色对勾 PNG（复选框选中态用），返回可供 QSS url() 使用的路径。
    用 QImage 而非 QPixmap：模块导入时 QApplication 还不存在。"""
    try:
        path = os.path.join(tempfile.gettempdir(), f"vrcosc_check_{os.getpid()}.png")
        if not os.path.exists(path):
            from PyQt5.QtGui import QImage
            img = QImage(12, 12, QImage.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor("#ffffff"), 2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([QPoint(2, 6), QPoint(5, 9), QPoint(10, 3)])
            p.end()
            if not img.save(path, "PNG"):
                return None
        return path.replace("\\", "/")
    except Exception:
        return None


_CHECK_PNG = _ensure_check_png()


# ============================================================
# 配色主题 - 预设色板，清新绿为默认（排第一）
# 原理：模板硬编码的是绿色系，其它主题对整个绿色系做色相偏移，
# 保持明度/饱和度结构不变，得到协调的同系配色
# ============================================================
# 需要随主题变化的绿色系 hex（模板与代码里的绿色字面量）
_GREEN_HEX = [
    "#f0f8f0", "#1a3a1a", "#6b8f6b", "#527052",
    "#2da44e", "#34c759", "#1a7a37", "#2cb359", "#269a45",
    "#ebf5eb", "#e4eee4", "#93ab93", "#d4e8d4", "#c0dec0",
    "#b0d4b0", "#dcecdc", "#9db89d", "#b0c8b0", "#c0d4c0",
    "#8fb58f", "#d4e4d4", "#9fd8ac", "#8fae95", "#cfe8d4",
    "#e8f5ea", "#eef7ef", "#f5fff5", "#7ee787", "#7fa387",
    "#3a4a3c",
]
# 需要随主题变化的绿色系 rgb 三元组（出现在 rgba(...) 里）
_GREEN_RGB = [
    "245, 255, 245", "248, 253, 248", "45, 164, 78",
    "52, 199, 89", "126, 231, 135",
]
# 极光背景色（底色 + 3 个光球）
_AURORA_GREEN = [
    (240, 248, 240), (120, 200, 130), (100, 220, 180), (180, 220, 100),
]

THEMES = {
    "green":  {"name": "清新绿", "accent": "#2da44e"},
    "blue":   {"name": "天空蓝", "accent": "#0a84ff"},
    "purple": {"name": "薰衣草", "accent": "#5856d6"},
    "teal":   {"name": "青碧",   "accent": "#00a6a0"},
    "orange": {"name": "珊瑚橙", "accent": "#ff7a1a"},
    "pink":   {"name": "玫瑰粉", "accent": "#ff2d55"},
}

CURRENT_THEME = "green"
# 当前主题的强调色（供电平条/历史闪光等代码读取）
CURRENT_ACCENT_HEX = "#2da44e"
CURRENT_ACCENT_RGB = (52, 199, 89)


def _hex2hls(hexv):
    h = hexv.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return rgb_to_hls(r, g, b)


def _hex2rgb(hexv):
    h = hexv.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hls2hex(h, l, s):
    r, g, b = hls_to_rgb(h % 1.0, l, s)
    return "#%02x%02x%02x" % (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _lighten(hexv, dl):
    """调整明度（dl 为 -1..1 的增量），保持色相/饱和度。"""
    h, l, s = _hex2hls(hexv)
    return _hls2hex(h, min(1.0, max(0.0, l + dl)), s)


def _shift_hex(hexv, dh):
    h, l, s = _hex2hls(hexv)
    return _hls2hex(h + dh, l, s)


def _shift_rgb(rgbstr, dh):
    r, g, b = (int(x) / 255.0 for x in rgbstr.split(","))
    h, l, s = rgb_to_hls(r, g, b)
    r, g, b = hls_to_rgb((h + dh) % 1.0, l, s)
    return "%d, %d, %d" % (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _theme_hue_shift(theme_id):
    """相对默认绿色主题的色相偏移量。"""
    gh, _, _ = _hex2hls(THEMES["green"]["accent"])
    th, _, _ = _hex2hls(THEMES.get(theme_id, THEMES["green"])["accent"])
    return th - gh


def build_stylesheet(theme_id):
    """按主题构建主样式表和弹层样式表。"""
    dh = _theme_hue_shift(theme_id)
    sheet = _STYLE_SHEET_TEMPLATE
    popup = POPUP_VIEW_QSS
    if dh != 0.0:
        for h in _GREEN_HEX:
            sheet = sheet.replace(h, _shift_hex(h, dh))
            popup = popup.replace(h, _shift_hex(h, dh))
        for rgb in _GREEN_RGB:
            sheet = sheet.replace(rgb, _shift_rgb(rgb, dh))
            popup = popup.replace(rgb, _shift_rgb(rgb, dh))
    if _CHECK_PNG:
        sheet = sheet.replace("__CHECK_URL__", _CHECK_PNG)
    else:
        sheet = sheet.replace("    image: url(__CHECK_URL__);\n", "")
    return sheet, popup


def aurora_colors(theme_id):
    """按主题返回极光底色 + 3 个光球颜色。"""
    dh = _theme_hue_shift(theme_id)
    out = []
    for (r, g, b) in _AURORA_GREEN:
        h, l, s = rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        nr, ng, nb = hls_to_rgb((h + dh) % 1.0, l, s)
        out.append((int(round(nr * 255)), int(round(ng * 255)), int(round(nb * 255))))
    return out


def apply_theme(theme_id):
    """切换主题：重建样式表并更新模块级强调色，返回 (sheet, popup)。"""
    global CURRENT_THEME, CURRENT_ACCENT_HEX, CURRENT_ACCENT_RGB
    CURRENT_THEME = theme_id if theme_id in THEMES else "green"
    dh = _theme_hue_shift(CURRENT_THEME)
    # 强调色与样式表完全一致：默认 #2da44e 做色相偏移（绿色主题原样，其它主题同构偏移）
    CURRENT_ACCENT_HEX = _shift_hex("#2da44e", dh)
    # 强调亮色 #34c759（电平条轨道/闪光/弹窗边框）随主题色相偏移后转 rgb
    CURRENT_ACCENT_RGB = _hex2rgb(_shift_hex("#34c759", dh))
    return build_stylesheet(CURRENT_THEME)


STYLE_SHEET, POPUP_VIEW_QSS_THEMED = apply_theme(CURRENT_THEME)


# ============================================================
# 动画基础设施
# 原则 (emil-design-eng / animate / apple-design):
# - 高频操作不加动画; UI 动画 < 300ms; 入场一律 ease-out
# - 只做 opacity / 位置入场, 不做布局属性动画
# - 尊重系统"减少动态效果"设置 (reduced motion = 更克制而非零动画)
# ============================================================
def _system_animations_enabled():
    """Windows: 读取系统"在 Windows 中显示动画"设置，关闭时只保留极短淡入淡出。"""
    if sys.platform != "win32":
        return True
    try:
        val = ctypes.c_int(1)
        SPI_GETCLIENTAREAANIMATION = 0x1042
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(val), 0
        )
        return bool(ok) and bool(val.value)
    except Exception:
        return True


MOTION_OK = _system_animations_enabled()
# VRC_UI_SLOWMO=4 可将所有动画放慢 4 倍，便于慢速检查动画细节
try:
    MOTION_SCALE = max(0.1, float(os.environ.get("VRC_UI_SLOWMO", "1") or 1))
except ValueError:
    MOTION_SCALE = 1.0


def _out_cubic():
    return QEasingCurve(QEasingCurve.OutCubic)


def fade_in(widget, duration=150, delay=0, finished=None):
    """淡入一个控件；结束后移除透明度特效，恢复原生渲染。
    若控件已有特效（被中断的淡出/淡入），从当前透明度续播，避免跳变。"""
    dur = max(1, int(duration * MOTION_SCALE))
    if not MOTION_OK:
        dur = min(dur, 80)
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        start_op = effect.opacity()
    else:
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        start_op = 0.0
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(dur)
    anim.setStartValue(start_op)
    anim.setEndValue(1.0)
    anim.setEasingCurve(_out_cubic())

    def _cleanup():
        # 被更新一次的淡入/淡出取代时，本轮回调作废（防止旧回调清掉新状态）
        if getattr(widget, "_ui_fade", None) is not anim:
            return
        try:
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)
        except RuntimeError:
            return
        if finished:
            finished()

    anim.finished.connect(_cleanup)
    widget._ui_fade = anim
    widget._ui_fade_dir = "in"
    if delay > 0:
        QTimer.singleShot(int(delay * MOTION_SCALE), anim.start)
    else:
        anim.start()
    return anim


def fade_out(widget, duration=100, finished=None):
    """淡出一个控件；结束后移除特效并回调（调用方再改文字/状态）。"""
    dur = max(1, int(duration * MOTION_SCALE))
    if not MOTION_OK:
        dur = min(dur, 60)
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(1.0)
        widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(dur)
    anim.setStartValue(effect.opacity())
    anim.setEndValue(0.0)
    anim.setEasingCurve(_out_cubic())

    def _cleanup():
        if getattr(widget, "_ui_fade", None) is not anim:
            return
        try:
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)
        except RuntimeError:
            pass
        if finished:
            finished()

    anim.finished.connect(_cleanup)
    widget._ui_fade = anim
    widget._ui_fade_dir = "out"
    anim.start()
    return anim


def is_fading_out(widget):
    """控件是否正处于淡出动画中（用于快速状态翻转时重新淡入）。"""
    return getattr(widget, "_ui_fade_dir", None) == "out" and \
        getattr(widget, "_ui_fade", None) is not None


def rise_fade_in(widget, duration=200, rise=12):
    """顶层窗口/对话框入场：windowOpacity 淡入 + 自下方 rise 像素上浮。
    顶层窗口用 windowOpacity（原生合成器路径），不用 QGraphicsOpacityEffect。"""
    dur = max(1, int(duration * MOTION_SCALE))
    if not MOTION_OK:
        dur = min(dur, 80)
        rise = 0

    widget.setWindowOpacity(0.0)
    opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
    opacity.setDuration(dur)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(_out_cubic())

    group = QParallelAnimationGroup(widget)
    group.addAnimation(opacity)
    if rise:
        p = widget.pos()
        widget.move(p.x(), p.y() + int(rise))
        pos = QPropertyAnimation(widget, b"pos", widget)
        pos.setDuration(dur)
        pos.setEasingCurve(_out_cubic())
        pos.setEndValue(p)
        group.addAnimation(pos)

    def _ensure_visible():
        widget.setWindowOpacity(1.0)  # 兜底：任何情况下不能停在半透明

    group.finished.connect(_ensure_visible)
    widget._ui_rise = group
    group.start()


def stagger_fade(widgets, duration=240, step=50, delay=0):
    """一组控件依次淡入（stagger 30-80ms），入场不位移，避免和布局打架。"""
    if not MOTION_OK:
        duration = 100
        step = 20
    for i, w in enumerate(widgets):
        try:
            fade_in(w, duration, delay=delay + i * step)
        except RuntimeError:
            continue


def start_pulse(widget, period=1400, min_opacity=0.8):
    """活动状态呼吸脉冲（录音中）。仅状态指示用途，停止时必须调用 stop_pulse。"""
    if not MOTION_OK:
        return
    stop_pulse(widget)
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(int(period * MOTION_SCALE))
    anim.setStartValue(1.0)
    anim.setKeyValueAt(0.5, min_opacity)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve(QEasingCurve.InOutSine))
    anim.setLoopCount(-1)
    anim.start()
    widget._pulse_anim = anim
    widget._pulse_effect = effect


def stop_pulse(widget):
    anim = getattr(widget, "_pulse_anim", None)
    if anim is not None:
        anim.stop()
    widget._pulse_anim = None
    widget._pulse_effect = None
    try:
        effect = widget.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


_FLASH_ANIMS = {}


def flash_history_item(item, duration=500):
    """新历史条目绿色高亮淡出（发送成功的反馈，偶发操作）。"""
    if not MOTION_OK:
        return
    lw = item.listWidget()
    if lw is None:
        return

    def _set_bg(alpha):
        try:
            ar, ag, ab = CURRENT_ACCENT_RGB
            c = QColor(ar, ag, ab, int(alpha))
            item.setBackground(QBrush(c))
        except RuntimeError:
            return

    anim = QVariantAnimation(lw)
    anim.setDuration(int(duration * MOTION_SCALE))
    anim.setStartValue(70.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(_out_cubic())
    anim.valueChanged.connect(_set_bg)

    def _cleanup():
        try:
            item.setBackground(QBrush(Qt.transparent))
        except RuntimeError:
            pass
        _FLASH_ANIMS.pop(id(item), None)

    anim.finished.connect(_cleanup)
    _FLASH_ANIMS[id(item)] = anim
    anim.start()


# ============================================================
# 麦克风实时音量条 - 录音时显示输入电平，方便排查"识别不到我说话"
# ============================================================
class MicLevelBar(QWidget):
    thresholdChanged = pyqtSignal(float)  # 拖动阈值箭头 -> 新最低触发音量
    """细长电平条：绿色常态，橙色接近削波，红色削波；带峰值保持标记。

    显示值用快攻慢放的追踪平滑（Apple 流体感）：上涨迅速跟手，
    回落缓慢收尾，颜色在绿→橙→红之间连续插值而非跳变。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0    # 引擎真实电平（目标值）
        self._disp = 0.0     # 显示电平（平滑追踪）
        self._peak = 0.0
        self._engine = None
        self._min_rms = 0.02
        self._keep_visible = False
        self._drag = False
        self.setFixedHeight(16)
        self.setMinimumWidth(120)
        self.setToolTip("拖动箭头调整最低触发音量（越右越不敏感）")
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps，追帧更顺滑
        self._timer.timeout.connect(self._poll)

    def start(self, engine):
        self._engine = engine
        self._level = 0.0
        self._disp = 0.0
        self._peak = 0.0
        self.setVisible(True)
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._engine = None
        self._disp = 0.0
        self._peak = 0.0
        if not self._keep_visible:
            self.setVisible(False)
        self.update()

    def _poll(self):
        raw = float(getattr(self._engine, "_level", 0.0) or 0.0)
        self._level = raw
        # 快攻慢放：上涨 45%/帧 跟手，回落 16%/帧 柔和收尾
        rise = 0.45 if raw > self._disp else 0.16
        self._disp += (raw - self._disp) * rise
        if abs(raw - self._disp) < 0.002:
            self._disp = raw
        # 峰值保持缓慢下落
        self._peak = max(self._peak - 0.006, self._disp)
        self.update()

    @staticmethod
    def _level_color(lvl):
        """主题色(≤0.6) → 橙(0.8) → 红(≥0.95) 连续插值。"""
        green = QColor(CURRENT_ACCENT_HEX)
        orange = QColor("#ff9500")
        red = QColor("#ff3b30")
        if lvl <= 0.6:
            return green
        if lvl >= 0.95:
            return red
        if lvl <= 0.8:
            t = (lvl - 0.6) / 0.2
            return QColor(
                round(green.red() + (orange.red() - green.red()) * t),
                round(green.green() + (orange.green() - green.green()) * t),
                round(green.blue() + (orange.blue() - green.blue()) * t),
            )
        t = (lvl - 0.8) / 0.15
        return QColor(
            round(orange.red() + (red.red() - orange.red()) * t),
            round(orange.green() + (red.green() - orange.green()) * t),
            round(orange.blue() + (red.blue() - orange.blue()) * t),
        )

    @staticmethod
    def _rms_to_pos(rms):
        import math as _m
        db = 20.0 * _m.log10(max(rms, 1e-5))
        return max(0.0, min(1.0, (db + 45.0) / 45.0))

    @staticmethod
    def _pos_to_rms(pos):
        db = pos * 45.0 - 45.0
        return max(0.001, min(0.1, 10.0 ** (db / 20.0)))

    def set_threshold(self, rms):
        self._min_rms = max(0.001, min(0.1, float(rms)))
        self.update()

    def threshold(self):
        return self._min_rms

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = True
            self._apply_pos(event.pos().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag:
            self._apply_pos(event.pos().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = False
        super().mouseReleaseEvent(event)

    def _apply_pos(self, x):
        w = max(1, self.width())
        pos = max(0.0, min(1.0, x / float(w)))
        rms = round(self._pos_to_rms(pos), 4)
        if abs(rms - self._min_rms) > 0.0005:
            self._min_rms = rms
            self.setToolTip("最低触发音量: %.3f" % rms)
            self.update()
            self.thresholdChanged.emit(rms)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        r = h / 2.0
        p.setPen(Qt.NoPen)
        # 底槽
        ar, ag, ab = CURRENT_ACCENT_RGB
        p.setBrush(QColor(ar, ag, ab, 36))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        # 电平填充（平滑追踪值）
        lw = w * max(0.0, min(1.0, self._disp))
        if lw > 0.5:
            p.setBrush(self._level_color(self._disp))
            p.drawRoundedRect(QRectF(0, 0, max(lw, h), h), r, r)
        # 峰值标记
        px = w * min(1.0, self._peak)
        if px > 2:
            p.setBrush(QColor(26, 58, 26, 110))
            p.drawRoundedRect(QRectF(px - 1, 1.5, 2, h - 3), 1, 1)
        # 最低触发音量阈值箭头（可拖动）
        from PyQt5.QtGui import QPolygonF
        tp = w * min(1.0, max(0.0, self._rms_to_pos(self._min_rms)))
        p.setBrush(QColor("#ff9500"))
        p.drawPolygon(QPolygonF([
            QPointF(tp - 5, h - 1), QPointF(tp + 5, h - 1), QPointF(tp, h - 9)]))
        p.drawRoundedRect(QRectF(tp - 1, 2, 2, h - 10), 1, 1)


# ============================================================
# 带展开动画的下拉框 - 弹出菜单淡入 + 自上而下展开（140ms ease-out）
# ============================================================
class AnimatedComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_anim = None

    def showPopup(self):
        if MOTION_OK:
            w = self.view().window()
            if w is not None:
                w.setWindowOpacity(0.0)  # show 前先藏住，避免首帧闪现
        super().showPopup()
        if not MOTION_OK:
            return
        popup = self.view().window()
        if popup is None:
            return
        final = QRect(popup.geometry())
        # 自上而下展开：起始只露出顶部一条，同时轻微上浮归位
        start_h = min(final.height(), 28)
        start = QRect(final.x(), final.y() - 3, final.width(), start_h)
        group = QParallelAnimationGroup(popup)
        geo = QPropertyAnimation(popup, b"geometry", popup)
        geo.setDuration(int(150 * MOTION_SCALE))
        geo.setStartValue(start)
        geo.setEndValue(QRect(final))
        geo.setEasingCurve(_out_cubic())
        op = QPropertyAnimation(popup, b"windowOpacity", popup)
        op.setDuration(int(110 * MOTION_SCALE))
        op.setStartValue(0.0)
        op.setEndValue(1.0)
        op.setEasingCurve(_out_cubic())
        group.addAnimation(geo)
        group.addAnimation(op)

        def _done():
            try:
                popup.setWindowOpacity(1.0)  # 兜底：不能停在透明
                popup.setGeometry(final)
            except RuntimeError:
                pass

        group.finished.connect(_done)
        group.start()
        self._popup_anim = group


# ============================================================
# 自绘标题栏 - 无边框窗口的拖拽/双击最大化 + 最小化/最大化/关闭按钮
# ============================================================
class TitleBar(QWidget):
    def __init__(self, main_window):
        super().__init__(main_window)
        self._win = main_window
        self._drag_offset = None
        self.setFixedHeight(42)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 5, 8, 5)
        lay.setSpacing(8)

        icon_label = QLabel()
        icon_path = os.path.join(RES_DIR, "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(APP_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(18, 18))
        icon_label.setFixedSize(18, 18)
        lay.addWidget(icon_label)

        title = QLabel(f"{APP_TITLE}  v{APP_VERSION}")
        title.setObjectName("winTitle")
        lay.addWidget(title)
        lay.addStretch()

        # macOS 红绿灯：常显彩色圆点，悬停时符号淡入
        self.min_btn = QPushButton("–")   # –
        self.max_btn = QPushButton("□")   # □
        self.close_btn = QPushButton("✕")  # ✕
        for b, name in ((self.min_btn, "tlMin"), (self.max_btn, "tlMax"),
                        (self.close_btn, "tlClose")):
            b.setObjectName(name)
            b.setFixedSize(16, 16)
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        lay.addSpacing(4)
        self.max_btn.setToolTip("最大化 / 还原（双击标题栏同效）")
        self.min_btn.setToolTip("最小化")
        self.close_btn.setToolTip("关闭")
        self.min_btn.clicked.connect(self._win.showMinimized)
        self.max_btn.clicked.connect(self._win.toggle_maximize)
        self.close_btn.clicked.connect(self._win.close)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not getattr(self._win, "_maxed", False):
            self._drag_offset = event.globalPos() - self._win.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self._win.move(event.globalPos() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._win.toggle_maximize()
        super().mouseDoubleClickEvent(event)


# ============================================================
# 无边框窗口边缘缩放 - 应用级事件过滤器，命中窗口边缘 5px 时启用手势
# ============================================================
class FramelessResizer(QObject):
    L, R, T, B = 1, 2, 4, 8
    MARGIN = 5

    def __init__(self, win):
        super().__init__(win)
        self._win = win
        self._edges = 0
        self._press = None
        self._geo0 = None
        QApplication.instance().installEventFilter(self)

    def _edge_at(self, gp, fg):
        m = self.MARGIN
        e = 0
        if gp.x() <= fg.left() + m:
            e |= self.L
        if gp.x() >= fg.right() - m:
            e |= self.R
        if gp.y() <= fg.top() + m:
            e |= self.T
        if gp.y() >= fg.bottom() - m:
            e |= self.B
        return e

    def _update_cursor(self, e):
        win = self._win
        if e == 0:
            win.unsetCursor()
        elif e in (self.T, self.B):
            win.setCursor(Qt.SizeVerCursor)
        elif e in (self.L, self.R):
            win.setCursor(Qt.SizeHorCursor)
        elif e in (self.L | self.T, self.R | self.B):
            win.setCursor(Qt.SizeFDiagCursor)
        else:
            win.setCursor(Qt.SizeBDiagCursor)

    def _do_resize(self, gp):
        win = self._win
        e = self._edges
        g = QRect(self._geo0)
        d = gp - self._press
        minw, minh = win.minimumWidth(), win.minimumHeight()
        if e & self.L:
            g.setX(min(g.x() + d.x(), g.right() - minw + 1))
        if e & self.R:
            g.setWidth(max(minw, g.width() + d.x()))
        if e & self.T:
            g.setY(min(g.y() + d.y(), g.bottom() - minh + 1))
        if e & self.B:
            g.setHeight(max(minh, g.height() + d.y()))
        win.setGeometry(g)

    def eventFilter(self, obj, ev):
        # 应用级过滤器会收到所有 QObject 的事件；非控件对象没有 window()，
        # 对它们调用会抛 AttributeError，PyQt5 会 qFatal 直接杀进程
        if not isinstance(obj, QWidget):
            return False
        win = self._win
        try:
            if obj.window() is not win or getattr(win, "_maxed", False):
                return False
        except RuntimeError:
            return False
        t = ev.type()
        if t not in (QEvent.MouseMove, QEvent.MouseButtonPress,
                     QEvent.MouseButtonRelease, QEvent.Leave):
            return False
        # 滚动条贴着窗口右缘，不能吞掉它的点击
        if isinstance(obj, QScrollBar):
            return False
        gp = QCursor.pos()
        fg = win.frameGeometry()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            e = self._edge_at(gp, fg)
            if e:
                self._edges = e
                self._press = gp
                self._geo0 = QRect(fg)
                return True
        elif t == QEvent.MouseMove:
            if self._press:
                self._do_resize(gp)
                return True
            self._update_cursor(self._edge_at(gp, fg))
        elif t == QEvent.MouseButtonRelease and self._press:
            self._press = None
            self._edges = 0
            win.unsetCursor()
        elif t == QEvent.Leave and not self._press:
            win.unsetCursor()
        return False


# ============================================================
# Edge 在线语音识别 - subprocess 管理 C# WebView2 宿主
# ============================================================
EDGE_LANG_MAP = {
    "zh": "zh-CN", "en": "en-US", "ja": "ja-JP",
    "ko": "ko-KR", "yue": "zh-HK", "auto": "zh-CN",
}

def _edge_host_exe():
    """定位 EdgeSpeechHost.exe：源码时在 edge_host/publish，打包后在 _MEIPASS/edge_host。"""
    cands = [
        os.path.join(RES_DIR, "edge_host", "EdgeSpeechHost.exe"),
        os.path.join(APP_DIR, "edge_host", "EdgeSpeechHost.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge_host",
                     "bin", "Release", "net8.0-windows", "win-x64", "publish", "EdgeSpeechHost.exe"),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None

class EdgeRecognizer:
    """Edge 在线识别（WebView2 + Web Speech API），stdin/stdout JSON 通信。"""
    def __init__(self):
        self._proc = None
        self._reader = None
        self._lock = threading.Lock()
        self.on_result = None
        self.on_error = None
        self.on_listening = None
        self._ready = False
        self._start_pending = None  # (lang,)

    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self, lang="zh-CN"):
        with self._lock:
            if self.running():
                self._send({"cmd": "start", "lang": lang})
                return
            exe = _edge_host_exe()
            if not exe:
                if self.on_error: self.on_error("未找到 EdgeSpeechHost.exe")
                return
            CREATE_NO_WINDOW = 0x08000000
            self._proc = subprocess.Popen(
                [exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                creationflags=CREATE_NO_WINDOW)
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            self._start_pending = (lang,)

    def stop(self):
        with self._lock:
            if self.running():
                self._send({"cmd": "exit"})
            self._proc = None
            self._ready = False

    def set_lang(self, lang):
        self._send({"cmd": "set_lang", "lang": lang})

    def _send(self, obj):
        try:
            if self.running():
                self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
        except Exception:
            pass

    def _read_loop(self):
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line: continue
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                t = m.get("type")
                if t == "result":
                    txt = (m.get("text") or "").strip()
                    if txt and self.on_result: self.on_result(txt)
                elif t == "listening":
                    self._ready = True
                    if self.on_listening: self.on_listening()
                elif t == "error":
                    if self.on_error: self.on_error(m.get("code") or m.get("msg") or "edge-error")
                elif t == "started":
                    self._ready = True
                    with self._lock:
                        if self._start_pending:
                            lang = self._start_pending
                            self._start_pending = None
                            self._send({"cmd": "start", "lang": lang[0]})
        except Exception:
            pass

# ============================================================
# 扬声器悬浮翻译引擎 - 捕获扬声器回环音频 → 能量切段 → 识别 → 翻译
# 与麦克风 VoiceEngine 完全独立（各自的模型实例和线程），可同时运行
# ============================================================
class SpeakerEngine(QObject):
    partialResult = pyqtSignal(str)      # 识别到的原文
    translated = pyqtSignal(str, str)    # (原文, 译文；译文失败时为空串)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finishedSig = pyqtSignal()

    def __init__(self, translator):
        super().__init__()
        self._translator = translator
        self._recognizer = None
        self._segmenter = None
        self._shared = None  # 借用麦克风识别器（语言一致时）
        self._shared_lang_hint = None  # 共享识别器对应的语言
        self._running = False
        self._loaded_lang = None  # 识别器当前加载的语言
        self._gen = 0  # 代际计数：热切换输出设备时作废旧工作线程
        self._device_index = None
        self._lang = "auto"
        self._target = "zh"
        self._level = 0.0  # 归一化捕获电平 (0..1)，悬浮窗音量条轮询用
        self._paused = False  # 暂停捕获（跳过切分与识别，仍刷新电平）
        self._min_rms = 0.02  # 音量阈值（RMS），主窗口设置里同步
        self._enable_denoiser = True  # 识别前降噪（GTCRN）
        self._denoiser = None
        self._reload_busy = False  # 后台重建识别器进行中
        self._tq = queue.Queue(maxsize=8)
        self._tr_running = False

    def set_langs(self, lang, target):
        """实时切换源语言/目标语言（识别器语言在下次加载模型时生效）。"""
        self._lang = lang or "auto"
        self._target = target or "zh"

    def start(self, device_index, lang, target, shared_recognizer=None):
        """device_index: pyaudiowpatch 回环设备索引；None = 默认输出的回环。
        shared_recognizer: 语言一致时可借用麦克风识别器，省一份模型内存。"""
        self._gen += 1
        my_gen = self._gen
        self._device_index = device_index
        self.set_langs(lang, target)
        self._level = 0.0
        if shared_recognizer is not None:
            self._shared = shared_recognizer
            self._shared_lang_hint = lang
            self._recognizer = None
        else:
            self._shared = None
            self._recognizer = None
            self._loaded_lang = None  # 触发后台加载自有模型
        self._running = True
        self._tr_running = True
        threading.Thread(target=self._worker, args=(my_gen,), daemon=True).start()
        threading.Thread(target=self._translator_worker, daemon=True).start()

    def set_paused(self, paused):
        self._paused = bool(paused)

    def stop(self):
        self._gen += 1
        self._running = False
        self._tr_running = False
        self._shared = None
        self._recognizer = None
        self._shared_lang_hint = None
        self._loaded_lang = None

    def _build_recognizer(self, lang):
        """构建识别器（慢操作，需在后台线程调用）。"""
        if not os.path.exists(ASR_MODEL):
            raise FileNotFoundError(f"找不到语音识别模型: {ASR_MODEL}")
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=ASR_MODEL,
            tokens=ASR_TOKENS,
            num_threads=2,
            use_itn=True,
            language=lang,
        )

    def _maybe_reload(self):
        """源语言变化或缺少识别器时，后台重建识别器并原子换入（不阻塞捕获）。"""
        if getattr(self, "_reload_busy", False):
            return
        # 已就绪且语言一致 → 无需处理
        if self._recognizer is not None and self._loaded_lang == self._lang:
            return
        # 共享识别器可用且语言一致 → 直接采用，省内存
        if self._shared is not None and getattr(self, "_shared_lang_hint", None) == self._lang:
            self._recognizer = self._shared
            self._loaded_lang = self._lang
            return
        self._reload_busy = True
        lang = self._lang

        def _work():
            try:
                self.status.emit("正在加载翻译模型...")
                rec = self._build_recognizer(lang)
                self._recognizer = rec  # 原子换入
                self._shared = None
                self._loaded_lang = lang
            except Exception as e:
                self.error.emit(f"模型加载失败: {e}")
            finally:
                self._reload_busy = False

        threading.Thread(target=_work, daemon=True).start()

    def _worker(self, my_gen):
        try:
            if not _HAS_SPEAKER_LIB:
                raise RuntimeError("缺少 pyaudiowpatch 库，请重新安装本程序")
            # 分段器（与识别器独立；识别器可能在后台加载/切换）
            self._segmenter = _EnergySegmenter(
                sr=SAMPLE_RATE, gain=1.4, min_speech=0.3, min_silence=0.7, max_speech=10.0,
                min_rms=self._min_rms
            )
            self._maybe_reload()
            p = pyaudio_wp.PyAudio()
            try:
                if self._device_index is not None:
                    loop = p.get_device_info_by_index(self._device_index)
                else:
                    wasapi = p.get_host_api_info_by_type(pyaudio_wp.paWASAPI)
                    out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                    loop = out if out.get("isLoopbackDevice") else None
                    if loop is None:
                        for lb in p.get_loopback_device_info_generator():
                            if out["name"] in lb["name"]:
                                loop = lb
                                break
                if loop is None:
                    raise RuntimeError("找不到扬声器的回环设备")
                rate = int(loop["defaultSampleRate"])
                ch = loop["maxInputChannels"]
                if self._gen != my_gen:
                    return  # 已被热切换/停止作废
                self.status.emit(f"正在捕获: {loop['name'].replace(' [Loopback]', '')}")
                stream = p.open(
                    format=pyaudio_wp.paInt16,
                    channels=ch,
                    rate=rate,
                    frames_per_buffer=int(rate * 0.1),
                    input=True,
                    input_device_index=loop["index"],
                )
                try:
                    while self._running and self._gen == my_gen:
                        self._maybe_reload()
                        # 优先共享（麦克风）识别器；模型加载中先累积音频不丢内容
                        recognizer = self._shared if self._shared is not None else self._recognizer
                        data = stream.read(int(rate * 0.1), exception_on_overflow=False)
                        x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                        if ch > 1:
                            x = x.reshape(-1, ch).mean(axis=1)
                        mono = _resample_linear(x, rate, SAMPLE_RATE)
                        # 归一化电平（-45dB..0dB 映射），供悬浮窗音量条
                        rms = float(np.sqrt(np.mean(mono * mono))) if len(mono) else 0.0
                        db = 20.0 * math.log10(rms + 1e-7)
                        norm = max(0.0, min(1.0, (db + 45.0) / 45.0))
                        prev = self._level
                        self._level = norm if norm >= prev else prev * 0.85 + norm * 0.15
                        if self._segmenter is None or recognizer is None:
                            continue
                        if self._paused:
                            continue  # 暂停：丢弃音频，电平条照常刷新
                        self._segmenter.accept(mono)
                        for seg in self._segmenter.pop_segments():
                            self._recognize_with(recognizer, seg)
                finally:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                # 收尾：把未闭合的段冲出来识别
                if self._segmenter is not None and self._gen == my_gen:
                    self._segmenter.flush()
                    rec = self._shared if self._shared is not None else self._recognizer
                    for seg in self._segmenter.pop_segments():
                        if rec is not None:
                            self._recognize_with(rec, seg)
            finally:
                p.terminate()
        except Exception as e:
            if self._gen == my_gen:
                self.error.emit(f"扬声器捕获失败: {e}")
        finally:
            if self._gen == my_gen:
                self._running = False
                self.finishedSig.emit()

    def _recognize_with(self, recognizer, samples):
        try:
            samples = _maybe_denoise(self, samples)
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            recognizer.decode_stream(stream)
            text = stream.result.text.strip()
            if not _is_real_speech(text):
                self.status.emit("（这段没识别到清晰语音）")
                return
            self.partialResult.emit(text)
            try:
                self._tq.put_nowait(text)
            except queue.Full:
                pass  # 翻译跟不上时丢弃新段，避免延迟滚雪球
        except Exception:
            pass

    def _translator_worker(self):
        while self._tr_running:
            try:
                text = self._tq.get(timeout=0.5)
            except queue.Empty:
                continue
            translated = ""
            # 免费接口偶发限流/超时，失败最多重试 2 次（退避递增）
            for attempt in range(3):
                try:
                    translated, err = self._translator.translate(
                        text, voice_lang_to_baidu(self._lang), self._target
                    )
                    if err:
                        translated = ""
                except Exception:
                    translated = ""
                if translated or not self._tr_running:
                    break
                self.status.emit(f"翻译接口暂时失败，正在重试({attempt + 1}/2)...")
                time.sleep(1.2 * (attempt + 1))
            if not self._tr_running:
                break
            self.translated.emit(text, translated)


# ============================================================
# 悬浮翻译窗 - 深色玻璃、置顶、可拖动，实时显示 原文→译文
# ============================================================
class FloatingTranslateWindow(QWidget):
    closedByUser = pyqtSignal()  # 用户点 ✕：主窗口应停止引擎并复位按钮
    pauseToggled = pyqtSignal(bool)  # 用户点 ⏸：暂停/继续捕获

    def __init__(self):
        super().__init__(
            None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(400, 320)
        self._drag_offset = None
        self._pending_original = None

        card = QFrame(self)
        card.setObjectName("floatCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)

        # ---- 头部：标题 + 语言选择 + 关闭 ----
        head = QHBoxLayout()
        head.setSpacing(6)
        dot = QLabel("🌐")
        title = QLabel("悬浮翻译")
        title.setObjectName("floatTitle")
        head.addWidget(dot)
        head.addWidget(title)
        head.addStretch()

        self.source_combo = AnimatedComboBox()
        self.source_combo.setObjectName("floatCombo")
        for label, code in LANGUAGES:
            self.source_combo.addItem(label, code)
        self.source_combo.setToolTip("扬声器里的语音语言")
        head.addWidget(self.source_combo)

        arrow = QLabel("→")
        arrow.setObjectName("floatTitle")
        head.addWidget(arrow)

        self.target_combo = AnimatedComboBox()
        self.target_combo.setObjectName("floatCombo")
        # 翻译方向固定为 其他语言 → 中文，中文排在首位作为默认
        for label, code in [("中文", "zh")] + TRANSLATE_LANGS:
            self.target_combo.addItem(label, code)
        self.target_combo.setToolTip("翻译目标语言")
        head.addWidget(self.target_combo)

        self.pause_btn = QPushButton("\u23F8")  # ⏸
        self.pause_btn.setObjectName("floatBtn")
        self.pause_btn.setFixedSize(24, 24)
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setToolTip("暂停/继续捕获")
        head.addWidget(self.pause_btn)

        self.close_btn = QPushButton("\u2715")
        self.close_btn.setObjectName("floatBtn")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("关闭悬浮窗")
        head.addWidget(self.close_btn)
        lay.addLayout(head)

        # ---- 输出设备选择行（游戏/音乐可能不走默认输出设备）----
        dev_row = QHBoxLayout()
        dev_row.setSpacing(6)
        dev_label = QLabel("捕获:")
        dev_label.setObjectName("floatStatus")
        dev_row.addWidget(dev_label)
        self.device_combo = AnimatedComboBox()
        self.device_combo.setObjectName("floatCombo")
        self.device_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.device_combo.setToolTip("选择要捕获哪个扬声器/输出设备的音频")
        dev_row.addWidget(self.device_combo, 1)
        lay.addLayout(dev_row)

        # ---- 捕获电平条：条子没动说明选错了设备或没有声音 ----
        self.level_bar = MicLevelBar()
        self.level_bar.setVisible(False)
        lay.addWidget(self.level_bar)

        # ---- 状态行（识别中提示/错误）----
        self.status_label = QLabel("等待启动...")
        self.status_label.setObjectName("floatStatus")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        # ---- 正文：原文→译文 流 ----
        self.body = QTextEdit()
        self.body.setObjectName("floatBody")
        self.body.setReadOnly(True)
        lay.addWidget(self.body, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self.close_btn.clicked.connect(self._on_user_close)
        self.pause_btn.clicked.connect(self._toggle_pause)

    # ---- 对外接口 ----
    def set_langs(self, source, target):
        # 源语言默认中文（用户主要翻译英文游戏语音，中文声源极少需要 auto 误判）
        if source is None or source == "auto":
            source = "zh"
        for combo, code in ((self.source_combo, source), (self.target_combo, target)):
            if code is None:
                continue
            for i in range(combo.count()):
                if combo.itemData(i) == code:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(i)
                    combo.blockSignals(False)
                    break

    def source_lang(self):
        return self.source_combo.currentData() or "auto"

    def target_lang(self):
        return self.target_combo.currentData() or "zh"

    def set_devices(self, devices, selected_index=None):
        """填充输出设备下拉框。devices: [(显示名, 设备索引)]。"""
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for label, idx in devices:
            self.device_combo.addItem(label, idx)
        if selected_index is not None:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == selected_index:
                    self.device_combo.setCurrentIndex(i)
                    break
        self.device_combo.blockSignals(False)

    def current_device_index(self):
        return self.device_combo.currentData()

    def current_device_name(self):
        return self.device_combo.currentText()

    def start_meter(self, engine):
        """显示捕获电平条并开始轮询引擎电平。"""
        self.level_bar.start(engine)

    def stop_meter(self):
        self.level_bar.stop()
        self.level_bar.setVisible(False)

    def show_at(self, geo):
        # 取消正在进行的退场淡出：快速"停止→再打开"时，
        # 淡出完成的回调会把刚打开的窗口藏掉
        self._fade_closing = False
        fade = getattr(self, "_fade_anim", None)
        try:
            if fade is not None and fade.state() == QPropertyAnimation.Running:
                fade.stop()
        except RuntimeError:
            pass
        if geo and len(geo) == 4:
            x, y, w, h = geo
            if w == self.width() and h == self.height():
                self.move(x, y)
        self.show()
        self.raise_()
        self._play_entrance()

    def _play_entrance(self):
        """Apple 式入场：淡入 + 从 92% 放大到位 + 8px 上浮（绝不从 0 开始）。"""
        if not MOTION_OK:
            self.setWindowOpacity(1.0)
            return
        final = self.geometry()
        w, h = final.width(), final.height()
        start = QRect(
            final.x() + int(w * 0.04), final.y() + 8 + int(h * 0.04),
            int(w * 0.92), int(h * 0.92),
        )
        self.setWindowOpacity(0.0)
        group = QParallelAnimationGroup(self)
        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(int(260 * MOTION_SCALE))
        geo_anim.setStartValue(start)
        geo_anim.setEndValue(QRect(final))
        # 几何带一点落定回弹（overshoot 0.6 ≈ 3%），透明度不带
        ease = QEasingCurve(QEasingCurve.OutBack)
        ease.setOvershoot(0.6)
        geo_anim.setEasingCurve(ease)
        op_anim = QPropertyAnimation(self, b"windowOpacity", self)
        op_anim.setDuration(int(200 * MOTION_SCALE))
        op_anim.setStartValue(0.0)
        op_anim.setEndValue(1.0)
        op_anim.setEasingCurve(_out_cubic())
        group.addAnimation(geo_anim)
        group.addAnimation(op_anim)

        def _done():
            self.setWindowOpacity(1.0)  # 兜底：任何情况不停在半透明

        group.finished.connect(_done)
        self._entrance_anim = group
        group.start()

    def fade_hide(self):
        """退场：150ms 淡出（比入场快），结束后真正隐藏。"""
        if not self.isVisible():
            return
        if not MOTION_OK:
            self.hide()
            return
        self._fade_closing = True
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(int(150 * MOTION_SCALE))
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(_out_cubic())

        def _done():
            # 期间被重新打开（_fade_closing 被置 False）则不隐藏
            if getattr(self, "_fade_closing", False):
                self.hide()
                self.setWindowOpacity(1.0)

        anim.finished.connect(_done)
        self._fade_anim = anim
        anim.start()

    def clear_stream(self):
        self.body.clear()
        self._pending_original = None

    def add_pending(self, text):
        """识别到原文、翻译还没回来时先提示。"""
        self._pending_original = text
        self.status_label.setText(f"🔊 {text}（翻译中…）")

    def add_pair(self, original, translated):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        esc = (original or "").replace("&", "&amp;").replace("<", "&lt;")
        if translated:
            tesc = translated.replace("&", "&amp;").replace("<", "&lt;")
            block = (
                f'<span style="color:#7fa387;font-size:8pt;">{stamp}</span><br>'
                f'<span style="color:#eef7ef;">{esc}</span><br>'
                f'<span style="color:#7ee787;">{tesc}</span>'
            )
        else:
            block = (
                f'<span style="color:#7fa387;font-size:8pt;">{stamp}</span><br>'
                f'<span style="color:#eef7ef;">{esc}</span><br>'
                f'<span style="color:#ffb46b;">（翻译失败，仅显示原文）</span>'
            )
        self.body.append(block)
        self.body.append("<span style=\"color:#3a4a3c;\">—</span>")
        self._pending_original = None
        self.status_label.setText("正在监听扬声器...")
        sb = self.body.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_float_status(self, text):
        self.status_label.setText(text)

    def _toggle_pause(self):
        paused = not getattr(self, "_ui_paused", False)
        self._ui_paused = paused
        self.pause_btn.setText("▶" if paused else "⏸")
        self.pause_btn.setToolTip("继续捕获" if paused else "暂停捕获")
        self.status_label.setText("已暂停捕获" if paused else "继续捕获中...")
        self.pauseToggled.emit(paused)

    def set_paused_ui(self, paused):
        """同步暂停按钮显示（如启动时）。"""
        self._ui_paused = bool(paused)
        self.pause_btn.setText("▶" if paused else "⏸")
        self.pause_btn.setToolTip("继续捕获" if paused else "暂停捕获")

    def save_geo(self):
        g = self.geometry()
        return [g.x(), g.y(), g.width(), g.height()]

    def _on_user_close(self):
        """用户点 ✕ = 完全停止：先淡出，再通知主窗口停引擎、复位按钮。"""
        self.fade_hide()
        self.closedByUser.emit()

    def closeEvent(self, event):
        # 无论哪种方式关闭，都要停掉电平条轮询计时器
        self.level_bar.stop()
        super().closeEvent(event)

    # ---- 拖动 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)



# ============================================================
# 历史列表换行代理 - 长条目自动换行，不再被硬裁剪
# ============================================================
class HistoryListDelegate(QStyledItemDelegate):
    """历史条目按列表宽度自动换行（最多 max_lines 行），完整内容走 tooltip。"""

    def __init__(self, view, max_lines=4):
        super().__init__(view)
        self._view = view
        self._max_lines = max_lines

    def sizeHint(self, option, index):
        text = index.data(Qt.DisplayRole) or ""
        fm = option.fontMetrics
        vw = max(60, self._view.viewport().width() - 22)
        rect = fm.boundingRect(0, 0, vw, 10000, Qt.TextWordWrap, text)
        line_h = fm.height()
        lines = max(1, round(rect.height() / line_h))
        h = min(lines, self._max_lines) * line_h
        return QSize(vw + 12, h + 10)


# ============================================================
# 淡绿色极光背景 - 直接在主窗口 paintEvent 绘制
# ============================================================
def paint_aurora_background(widget, event):
    """在主窗口背景上绘制淡色弥散光球（颜色随主题变化）。"""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)

    w, h = widget.width(), widget.height()
    if w == 0 or h == 0:
        return

    # 当前主题的极光配色（底色 + 3 光球）
    base, b1, b2, b3 = aurora_colors(CURRENT_THEME)

    # 底色
    painter.fillRect(event.rect(), QColor(base[0], base[1], base[2]))

    # 光球 1: 左上
    c1 = QRadialGradient(w * 0.15, h * 0.15, max(w, h) * 0.5)
    c1.setColorAt(0, QColor(b1[0], b1[1], b1[2], 80))
    c1.setColorAt(0.5, QColor(b1[0], b1[1], b1[2], 30))
    c1.setColorAt(1, QColor(b1[0], b1[1], b1[2], 0))
    painter.setBrush(QBrush(c1))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(w * 0.15, h * 0.15), w * 0.55, h * 0.55)

    # 光球 2: 右下
    c2 = QRadialGradient(w * 0.85, h * 0.8, max(w, h) * 0.5)
    c2.setColorAt(0, QColor(b2[0], b2[1], b2[2], 60))
    c2.setColorAt(0.5, QColor(b2[0], b2[1], b2[2], 20))
    c2.setColorAt(1, QColor(b2[0], b2[1], b2[2], 0))
    painter.setBrush(QBrush(c2))
    painter.drawEllipse(QPointF(w * 0.85, h * 0.8), w * 0.5, h * 0.5)

    # 光球 3: 中上
    c3 = QRadialGradient(w * 0.6, h * 0.3, max(w, h) * 0.35)
    c3.setColorAt(0, QColor(b3[0], b3[1], b3[2], 40))
    c3.setColorAt(1, QColor(b3[0], b3[1], b3[2], 0))
    painter.setBrush(QBrush(c3))
    painter.drawEllipse(QPointF(w * 0.6, h * 0.3), w * 0.35, h * 0.35)


class OSCSender:
    # Windows: 禁用 UDP 连接重置（ICMP port-unreachable 会让 socket 进入错误态，
    # 之后所有发送都失败，必须重启接收端/程序才能恢复——这正是“要在 VRChat 里重启 OSC”的根因）
    _SIO_UDP_CONNRESET = getattr(socket, "SIO_UDP_CONNRESET", 0x9800000C)

    def __init__(self):
        self._sock = None
        self._ip = DEFAULT_IP
        self._port = DEFAULT_PORT

    def connect(self, ip, port):
        self._ip = ip
        self._port = port
        self._reset_socket()

    def _reset_socket(self):
        """（重新）创建 UDP socket，并禁用 Windows 的 UDP 连接重置。"""
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if sys.platform == "win32":
                try:
                    s.ioctl(self._SIO_UDP_CONNRESET, 0)
                except Exception:
                    pass
            self._sock = s
        except Exception:
            self._sock = None

    def _send(self, address, args):
        """发送 OSC 消息；失败时重建 socket 重试一次（VRChat 后开 OSC 也能自动恢复）。"""
        if self._sock is None:
            self._reset_socket()
        if self._sock is None:
            return False
        try:
            builder = OscMessageBuilder(address=address)
            for a in args:
                builder.add_arg(a)
            dgram = builder.build().dgram
            self._sock.sendto(dgram, (self._ip, self._port))
            return True
        except Exception:
            self._reset_socket()
            if self._sock is None:
                return False
            try:
                self._sock.sendto(dgram, (self._ip, self._port))
                return True
            except Exception:
                return False

    def send_chatbox(self, text, send_immediately=True, notify=False):
        return self._send("/chatbox/input", [text, send_immediately, notify])

    def send_typing(self, is_typing):
        if self._sock is None:
            return
        self._send("/chatbox/typing", [is_typing])


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

# pyaudiowpatch 为可选依赖（扬声器回环捕获用），未安装时功能入口给出提示
try:
    import pyaudiowpatch as pyaudio_wp
    _HAS_SPEAKER_LIB = True
except Exception:
    pyaudio_wp = None
    _HAS_SPEAKER_LIB = False


def _has_real_text(text):
    """剔除空白、标点、符号后是否还有实际文字。

    识别结果有时只剩 "。" 或单个感叹号——这类结果直接按未识别处理，
    不发送、不翻译、不进历史。
    """
    if not text:
        return False
    return bool(re.sub(r"[\W_]+", "", text, flags=re.UNICODE))


# 纯语气词（嗯/呃/啊之类）——背景噪声被误切成段时常识别出这些，没有传达内容
_CJK_FILLER_RE = re.compile(r"[嗯呃啊哦噢喔唔诶欸唉哎呀嘛嘿哈哟呦]+")
_EN_FILLER_RE = re.compile(r"\b(?:um+|uh+|hmm+|ah+|oh+|erm+|huh+)\b", re.IGNORECASE)
_PUNCT_GAP_RE = re.compile(r"[，。,.!！?？、；;：:~\-—…\s]+")


# 纯语气词过滤开关（设置里可关）：关闭后只过滤纯符号，保留嗯哈哈这类真实应答
FILTER_FILLERS = True


def _is_real_speech(text):
    """识别结果分级过滤。

    - 纯符号（。、！、—— 等）：始终丢弃——真实说话几乎不会只发出标点，必是噪声；
    - 纯语气词（嗯、呃、哈哈 等）：按 FILTER_FILLERS 开关决定，开着过滤、关了保留；
    - 语气词开头带实际内容（"嗯，我们今天来聊聊"）：始终保留。
    """
    if not _has_real_text(text):
        return False
    if not FILTER_FILLERS:
        return True
    residue = _CJK_FILLER_RE.sub("", text)
    residue = _PUNCT_GAP_RE.sub(" ", residue)
    residue = _EN_FILLER_RE.sub("", residue)
    return _has_real_text(residue)


def voice_lang_to_baidu(lang_code):
    """将语音识别语言代码映射为百度翻译语言代码。"""
    mapping = {
        "zh": "zh", "en": "en", "ja": "jp",
        "ko": "kor", "yue": "yue", "auto": "auto",
    }
    return mapping.get(lang_code, "auto")


def _detect_lang_simple(text):
    """粗粒度语种检测（Unicode 区段），供不支持 auto 的翻译接口兜底。"""
    for ch in text:
        o = ord(ch)
        if 0x0E00 <= o <= 0x0E7F:
            return "th"
        if 0x0600 <= o <= 0x06FF:
            return "ar"
        if 0x0400 <= o <= 0x04FF:
            return "ru"
        if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            return "ko"
        if 0x3040 <= o <= 0x30FF:
            return "ja"
        if 0x4E00 <= o <= 0x9FFF:
            return "zh"
    return "en"


def _resample_linear(x, sr_in, sr_out):
    """线性插值重采样（回环捕获 48k -> 识别 16k 用，无 scipy 依赖）。"""
    if sr_in == sr_out:
        return x.astype(np.float32)
    n_out = int(len(x) * sr_out / sr_in)
    if n_out <= 0 or len(x) == 0:
        return np.zeros(0, dtype=np.float32)
    return np.interp(
        np.linspace(0.0, len(x) - 1.0, n_out),
        np.arange(len(x), dtype=np.float64),
        x,
    ).astype(np.float32)


def _load_denoiser():
    """加载 GTCRN 实时降噪模型（sherpa-onnx 官方生态，VRCTA 同款 gtcrn_simple.onnx）。"""
    if not os.path.exists(DENOISER_MODEL):
        return None
    try:
        cfg = sherpa_onnx.OfflineSpeechDenoiserConfig()
        cfg.model.gtcrn.model = DENOISER_MODEL
        cfg.model.num_threads = 2
        return sherpa_onnx.OfflineSpeechDenoiser(cfg)
    except Exception:
        return None


def _maybe_denoise(engine, samples):
    """识别前降噪（引擎启用降噪开关时）。失败静默回退原样，不阻断识别。"""
    if not getattr(engine, "_enable_denoiser", False):
        return samples
    dn = getattr(engine, "_denoiser", None)
    if dn is None:
        dn = _load_denoiser()
        try:
            engine._denoiser = dn
        except Exception:
            engine._denoiser = False
            return samples
    if dn in (None, False):
        return samples
    try:
        out = dn.run(samples, SAMPLE_RATE)
        res = np.asarray(out.samples, dtype=np.float32)
        return res if len(res) else samples
    except Exception:
        return samples


class _EnergySegmenter:
    """语音分段器（WebRTC VAD 帧判定，能量门限兜底）。

    sherpa-onnx 1.13.x 的 Silero VAD 在部分环境出段损坏（只产出 0 采样空段）。
    首选 WebRTC VAD（频谱特征判定，比纯能量抗噪得多）；webrtcvad 不可用时
    退回自适应噪声底能量门限。
    """

    def __init__(self, sr=16000, gain=1.4, min_speech=0.25,
                 min_silence=0.6, max_speech=10.0, preroll=0.7, min_rms=0.02):
        self.sr = sr
        self.gain = gain
        self.min_speech = min_speech
        self.min_silence = min_silence
        self.max_speech = max_speech
        self.min_rms = min_rms  # 绝对音量阈值：RMS 低于它不算语音
        self.in_speech = False  # 供 UI 说话状态显示
        self.segments = []
        self._speech_run = 0.0
        self._sil_run = 0.0
        self._in_speech = False
        self._seg_buf = []
        self._preroll_buf = []
        self.suppressed = False  # 持续音频（音乐）硬切后的反刷屏抑制
        self._quiet_run = 0.0

        # ---- WebRTC VAD（首选）----
        self._webrtc = None
        try:
            import webrtcvad
            self._webrtc = webrtcvad.Vad(3)  # 0-3，3=最激进（少误报）
            self._frame_samples = int(sr * 0.03)  # 30ms 帧
            self._frame_bytes_len = self._frame_samples * 2  # int16
            self._frame_acc = b""
            self._preroll_n = max(1, int(preroll / 0.03))
            self._w_noise = None  # 能量门限噪声底，首帧校准
            return
        except Exception:
            pass

        # ---- 能量门限兜底 ----
        self._preroll = int(preroll * sr / 512) or 1
        self._hist = deque(maxlen=250)
        self._smooth = None
        self._buf = []

    def accept(self, x):
        if self._webrtc is not None:
            pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            self._frame_acc += pcm
            flen = self._frame_bytes_len
            while len(self._frame_acc) >= flen:
                frame = self._frame_acc[:flen]
                self._frame_acc = self._frame_acc[flen:]
                self._process_webrtc_frame(frame)
            return
        self._accept_energy(x)

    def _process_webrtc_frame(self, frame_bytes):
        dur = self._frame_samples / self.sr
        arr = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        # 能量门限：WebRTC 判为语音但音量接近底噪的帧按静音处理，
        # 从根源上防"没说话也识别出字"（背景噪声被误判成语音）
        rms = float(np.sqrt(np.mean(arr * arr))) if len(arr) else 0.0
        if self._w_noise is None:
            self._w_noise = rms  # 首帧校准到实际环境底噪
        elif rms < self._w_noise:
            self._w_noise = rms * 0.9 + self._w_noise * 0.1
        else:
            self._w_noise = self._w_noise * 0.999  # 慢速上漂，不被短促声音拉高
        try:
            is_speech = self._webrtc.is_speech(frame_bytes, self.sr)
        except Exception:
            is_speech = False
        # 音量接近底噪（<1.5x）不算语音
        if is_speech and rms < max(self._w_noise * 1.5, self.min_rms, 0.003):
            is_speech = False
        if not self._in_speech:
            # 抑制期（持续音频硬切后）：等出现 0.4s 安静帧才恢复切分，防止节奏性刷歌词
            if self.suppressed:
                if is_speech:
                    self._quiet_run = 0.0
                else:
                    self._quiet_run += dur
                    if self._quiet_run >= 0.4:
                        self.suppressed = False
                        self._quiet_run = 0.0
                return
            self._preroll_buf.append(arr)
            if len(self._preroll_buf) > self._preroll_n:
                del self._preroll_buf[:-self._preroll_n]
            if is_speech:
                self._speech_run += dur
                if self._speech_run >= self.min_speech:
                    self._in_speech = True
                    self.in_speech = True
                    self._sil_run = 0.0
                    self._seg_buf = list(self._preroll_buf)
                    self._preroll_buf.clear()
            else:
                self._speech_run = max(0.0, self._speech_run - 1.2 * dur)
        else:
            self._seg_buf.append(arr)
            if is_speech:
                self._sil_run = 0.0
            else:
                self._sil_run += dur
            total = sum(len(a) for a in self._seg_buf) / self.sr
            if self._sil_run >= self.min_silence or total >= self.max_speech:
                seg = np.concatenate(self._seg_buf)
                hard_cut = self._sil_run < self.min_silence  # 没有安静间隙，到时长上限被硬切
                if self._sil_run >= self.min_silence and self._sil_run * self.sr < len(seg):
                    seg = seg[:len(seg) - int(self._sil_run * self.sr)]
                if len(seg) >= self.min_speech * self.sr:
                    self.segments.append(seg.astype(np.float32))
                self._seg_buf = []
                self._in_speech = False
                self.in_speech = False
                self._speech_run = 0.0
                self._sil_run = 0.0
                if hard_cut:
                    # 持续音频（音乐/长独白）：进入抑制期，等 0.4s 安静帧再恢复
                    self.suppressed = True
                    self._quiet_run = 0.0

    def _accept_energy(self, x):
        """能量门限兜底路径（webrtcvad 不可用时）。"""
        rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
        self._smooth = rms if self._smooth is None else 0.6 * self._smooth + 0.4 * rms
        lvl = self._smooth
        if not self._in_speech:
            self._hist.append(lvl)
            # 抑制期：等安静了才恢复（与 webrtc 路径同一策略）
            if self.suppressed:
                thr = max(self._noise * self.gain, self.min_rms)
                if lvl > thr:
                    self._quiet_run = 0.0
                else:
                    self._quiet_run += len(x) / self.sr
                    if self._quiet_run >= 0.4:
                        self.suppressed = False
                        self._quiet_run = 0.0
                return
        self._noise = max(min(self._hist), 0.003)
        thr = max(self._noise * self.gain, self.min_rms)
        dur = len(x) / self.sr
        if not self._in_speech:
            self._buf.append(x)
            if len(self._buf) > self._preroll:
                del self._buf[:-self._preroll]
            if lvl > thr:
                self._speech_run += dur
                if self._speech_run >= self.min_speech:
                    self._in_speech = True
                    self.in_speech = True
                    self._sil_run = 0.0
            else:
                self._speech_run = max(0.0, self._speech_run - 1.2 * dur)
        else:
            self._buf.append(x)
            if lvl > thr:
                self._sil_run = 0.0
            else:
                self._sil_run += dur
            total = sum(len(a) for a in self._buf) / self.sr
            if self._sil_run >= self.min_silence or total >= self.max_speech:
                seg = np.concatenate(self._buf)
                hard_cut = self._sil_run < self.min_silence
                if self._sil_run >= self.min_silence and self._sil_run * self.sr < len(seg):
                    seg = seg[:len(seg) - int(self._sil_run * self.sr)]
                if len(seg) >= self.min_speech * self.sr:
                    self.segments.append(seg.astype(np.float32))
                self._buf = []
                self._in_speech = False
                self.in_speech = False
                self._speech_run = 0.0
                self._sil_run = 0.0
                if hard_cut:
                    self.suppressed = True
                    self._quiet_run = 0.0

    def pop_segments(self):
        out, self.segments = self.segments, []
        return out

    def flush(self):
        """强制闭合当前未完成的段（停止/测试收尾时用）。"""
        buf = self._seg_buf if self._webrtc is not None else self._buf
        if buf:
            seg = np.concatenate(buf)
            if len(seg) >= self.min_speech * self.sr:
                self.segments.append(seg.astype(np.float32))
        self._seg_buf = []
        self._buf = []
        self._preroll_buf.clear()
        self._frame_acc = b""
        self._in_speech = False
        self.in_speech = False
        self._speech_run = 0.0
        self._sil_run = 0.0


def _obfuscate_secret(text):
    """轻量 XOR+Base64 混淆（非加密，防明文泄露/截图）。"""
    if not text:
        return ""
    raw = text.encode("utf-8")
    key = b"VRC-OSC-Chatbox"
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return base64.b64encode(out).decode("ascii")


def _deobfuscate_secret(stored):
    """反混淆；非混淆格式（旧明文）自动兼容返回原值。"""
    if not stored:
        return ""
    try:
        raw = base64.b64decode(stored.encode("ascii"))
        key = b"VRC-OSC-Chatbox"
        out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
        return out.decode("utf-8")
    except Exception:
        return stored  # 旧明文直接用


class BaiduTranslator:
    """双模式翻译器：
    1. 百度官方 API（需 AppID + 密钥，免费注册: fanyi-api.baidu.com）
    2. MyMemory 免费 API（无需密钥，作为备用）
    """

    def __init__(self):
        self._baidu_appid = ""
        self._baidu_secret = ""

    def set_credentials(self, appid, secret):
        """设置百度 API 凭据（secret 可为混淆格式或旧明文，自动兼容）。"""
        self._baidu_appid = appid or ""
        self._baidu_secret = _deobfuscate_secret(secret) if secret else ""

    def has_baidu_api(self):
        """是否配置了百度官方 API。"""
        return bool(self._baidu_appid and self._baidu_secret)

    def translate(self, text, from_lang="zh", to_lang="en"):
        """翻译文本，返回 (译文, 错误信息)。成功时错误为 None。"""
        if not text.strip():
            return "", None
        # 源语言就是目标语言时直接返回原文（如中文游戏语音 + 目标中文）
        if to_lang == "zh" and _detect_lang_simple(text) == "zh":
            return text, None
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
            if src == "auto":
                # MyMemory 不支持 auto 源语言，用粗粒度检测兜底
                src = _detect_lang_simple(text)
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

    def showEvent(self, event):
        super().showEvent(event)
        # 偶发操作的模态弹窗：200ms 淡入 + 12px 上浮（modal 居中，不做缩放原点）
        if not getattr(self, "_entered", False):
            self._entered = True
            rise_fade_in(self, duration=200, rise=12)

    def done(self, result):
        """关闭时 150ms 淡出再真正返回（退出比入场快）。"""
        if MOTION_OK and self.isVisible() and self.windowOpacity() > 0.95:
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(int(150 * MOTION_SCALE))
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(_out_cubic())

            def _fin():
                QDialog.done(self, result)

            anim.finished.connect(_fin)
            anim.start()
            self._close_anim = anim
            return
        QDialog.done(self, result)

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

        # 配色主题（第一个是默认清新绿）
        self.theme_combo = AnimatedComboBox()
        for tid, tinfo in THEMES.items():
            self.theme_combo.addItem(tinfo["name"], tid)
        cur_theme = self._cfg.get("theme", "green")
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == cur_theme:
                self.theme_combo.setCurrentIndex(i)
                break
        self.theme_combo.setToolTip("切换整体配色（按钮、焦点、极光背景等）")
        layout_form.addRow("配色主题:", self.theme_combo)

        # 行为选项
        self.autostart_chk = QCheckBox("开机自动启动")
        self.autostart_chk.setChecked(self._cfg.get("autostart", False))
        self.autostart_chk.setToolTip("登录 Windows 后自动运行（仅打包版生效）")
        layout_form.addRow("", self.autostart_chk)

        self.tray_chk = QCheckBox("关闭时最小化到托盘")
        self.tray_chk.setChecked(self._cfg.get("close_to_tray", False))
        self.tray_chk.setToolTip("点窗口关闭按钮时隐藏到系统托盘而不是退出")
        layout_form.addRow("", self.tray_chk)

        self.filter_filler_chk = QCheckBox("过滤纯语气词识别（嗯、哈哈等）")
        self.filter_filler_chk.setChecked(self._cfg.get("filter_fillers", True))
        self.filter_filler_chk.setToolTip("没说话时背景噪声会被误识别成语气词；取消勾选后只过滤纯符号，保留真实的“嗯”“哈哈”等应答")
        layout_form.addRow("", self.filter_filler_chk)

        layout.addWidget(layout_group)

        # ---- VAD 参数 ----
        vad_group = QGroupBox("语音检测参数 (VAD)")
        vad_form = QFormLayout(vad_group)

        # 最低触发音量：声音 RMS 超过该值才识别（越高越不敏感），0.001~0.1
        _vt = self._cfg.get("vad_threshold", 0.02)
        if not isinstance(_vt, (int, float)) or _vt > 0.15:
            _vt = 0.02  # 旧版灵敏度值（0.1~0.9）迁移为新音量阈值
        self.vad_threshold_slider = QSlider(Qt.Horizontal)
        self.vad_threshold_slider.setMinimum(1)
        self.vad_threshold_slider.setMaximum(100)
        self.vad_threshold_slider.setValue(int(_vt * 1000))
        self.vad_threshold_label = QLabel(f"{self.vad_threshold_slider.value() / 1000:.3f}")
        self.vad_threshold_slider.valueChanged.connect(
            lambda v: self.vad_threshold_label.setText(f"{v / 1000:.3f}")
        )
        vad_threshold_row = QHBoxLayout()
        vad_threshold_row.addWidget(self.vad_threshold_slider)
        vad_threshold_row.addWidget(self.vad_threshold_label)
        vad_form.addRow("最低触发音量:", vad_threshold_row)

        self.denoiser_chk = QCheckBox("识别前降噪（GTCRN）")
        self.denoiser_chk.setChecked(self._cfg.get("enable_denoiser", True))
        self.denoiser_chk.setToolTip("嘈杂环境下先降噪再识别，能减少误识别；会略微增加识别耗时")
        vad_form.addRow("", self.denoiser_chk)

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

        self.trans_lang_combo = AnimatedComboBox()
        for label, code in TRANSLATE_LANGS:
            self.trans_lang_combo.addItem(label, code)
        cur_target = self._cfg.get("translate_target", "en")
        for i in range(self.trans_lang_combo.count()):
            if self.trans_lang_combo.itemData(i) == cur_target:
                self.trans_lang_combo.setCurrentIndex(i)
                break
        trans_form.addRow("目标语言:", self.trans_lang_combo)

        self.trans_mode_combo = AnimatedComboBox()
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
        self._cfg["vad_threshold"] = self.vad_threshold_slider.value() / 1000
        self._cfg["min_silence_duration"] = self.silence_dur_slider.value() / 1000
        self._cfg["min_speech_duration"] = self.min_speech_slider.value() / 1000
        self._cfg["max_chars"] = self.max_chars_spin.value()
        self._cfg["translate_enabled"] = self.trans_enabled_chk.isChecked()
        self._cfg["translate_target"] = self.trans_lang_combo.currentData() or "en"
        self._cfg["translate_mode"] = self.trans_mode_combo.currentData() or "bilingual"
        self._cfg["baidu_appid"] = self.baidu_appid_edit.text().strip()
        self._cfg["baidu_secret"] = self.baidu_secret_edit.text().strip()
        self._cfg["autostart"] = self.autostart_chk.isChecked()
        self._cfg["close_to_tray"] = self.tray_chk.isChecked()
        self._cfg["enable_denoiser"] = self.denoiser_chk.isChecked()
        self._cfg["filter_fillers"] = self.filter_filler_chk.isChecked()
        self._cfg["theme"] = self.theme_combo.currentData() or "green"
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
        self._segmenter = None
        self._loaded_language = None  # 识别器当前加载的语言
        self._decode_lock = threading.Lock()  # 序列化解码，防并发错乱
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
        self._vad_threshold = 0.02  # 音量阈值（RMS），低于它不算语音
        self._min_silence_duration = 0.5
        self._min_speech_duration = 0.25
        self._max_speech_duration = 30
        self._level = 0.0  # 实时输入电平 (0..1)，UI 音量条轮询用
        self._enable_denoiser = False  # 识别前降噪（GTCRN）
        self._denoiser = None
        self._engine_type = "onnx"  # "onnx" 离线 SenseVoice / "edge" 在线 WebView2
        self._edge = None  # EdgeRecognizer 实例（惰性）
        self._edge_stop = threading.Event()
        # 连续模式状态
        self._in_speech = False

    def set_engine_type(self, engine_type):
        """切换识别引擎：onnx 离线 / edge 在线。运行中切换会在下次启动时生效。"""
        self._engine_type = engine_type or "onnx"

    def set_language(self, language):
        """更新识别语言（连续监听运行中也会在下一个音频块生效）。"""
        self._language = language or "zh"

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
        # 语言变更时重建识别器，让语言切换立即生效
        if self._recognizer is not None and self._loaded_language == self._language:
            return
        if not os.path.exists(ASR_MODEL):
            raise FileNotFoundError(f"找不到语音识别模型: {ASR_MODEL}")

        self.status.emit("正在加载语音模型...")
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=ASR_MODEL,
            tokens=ASR_TOKENS,
            num_threads=2,
            use_itn=True,
            language=self._language,
        )
        self._loaded_language = self._language
        # sherpa 1.13.x 的 Silero VAD 在部分环境出段损坏（只出 0 采样空段），
        # 连续监听改用能量分段器，设置里的参数映射过去
        self._segmenter = _EnergySegmenter(
            sr=SAMPLE_RATE,
            gain=2.0,
            min_speech=max(0.15, self._min_speech_duration * 0.8),
            min_silence=max(0.4, self._min_silence_duration * 0.9),
            max_speech=self._max_speech_duration,
            min_rms=self._vad_threshold,
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
        if self._engine_type == "edge":
            threading.Thread(target=self._edge_worker, daemon=True).start()
            return
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
        if self._engine_type == "edge":
            threading.Thread(target=self._edge_worker, daemon=True).start()
            return
        threading.Thread(target=self._continuous_worker, daemon=True).start()

    def stop(self):
        self._stop_flag = True
        self._edge_stop.set()

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
        self._level = 0.0  # 归一化输入电平，供 UI 音量条轮询

        def callback(in_data, frame_count, time_info, status):
            self._audio_queue.put(in_data)
            try:
                samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples * samples)))
                # -45dB..0dB 映射到 0..1，小声也能看出来
                db = 20.0 * math.log10(rms + 1e-7)
                norm = max(0.0, min(1.0, (db + 45.0) / 45.0))
                prev = self._level
                # 快攻慢放（EMA），电平条动起来自然
                self._level = norm if norm >= prev else prev * 0.85 + norm * 0.15
            except Exception:
                pass
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
    def _edge_worker(self):
        """Edge 在线识别流程：启动宿主→持续识别→回调 finalResult→等停止。"""
        try:
            if self._edge is None:
                self._edge = EdgeRecognizer()
                self._edge.on_result = self._on_edge_result
                self._edge.on_error = lambda e: self.error.emit("Edge识别: " + str(e))
            lang = EDGE_LANG_MAP.get(self._language, "zh-CN")
            self._edge_stop.clear()
            self._edge.start(lang)
            self.status.emit("Edge 在线识别中...")
            while self._running and not self._edge_stop.is_set():
                time.sleep(0.2)
        finally:
            if self._edge is not None:
                self._edge.stop()
            self._running = False
            self._in_speech = False
            self.pttFinished.emit()

    def _on_edge_result(self, text):
        """Edge 识别到的一句话 → 走和离线一样的后续（过滤+发送/填入）。"""
        if not _is_real_speech(text):
            return
        self.finalResult.emit(text)
        self.status.emit(f"识别: {text}")

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
            samples = _maybe_denoise(self, samples)

            stream = self._recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            self._recognizer.decode_stream(stream)
            text = stream.result.text.strip()

            if _is_real_speech(text):
                self.finalResult.emit(text)
                self.status.emit(f"识别完成: {text}")
            else:
                self.status.emit("未识别到有效语音内容")

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

                if self._language != self._loaded_language:
                    self._recognizer = None  # 语言切换 → 重建识别器
                    self._init_models()

                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                self._segmenter.accept(samples)

                # UI: 显示说话状态
                if self._segmenter.in_speech:
                    if not self._in_speech:
                        self._in_speech = True
                        self.vadState.emit(True)
                else:
                    if self._in_speech:
                        self._in_speech = False
                        self.vadState.emit(False)

                # 能量分段器凑出完整语音段后直接识别
                for audio in self._segmenter.pop_segments():
                    if len(audio) > SAMPLE_RATE * 0.15:  # 至少 0.15 秒
                        self._recognize_segment(audio)

            # 停止时 flush 剩余音频
            self._segmenter.accept(np.zeros(0, dtype=np.float32))
            for audio in self._segmenter.pop_segments():
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
                samples2 = _maybe_denoise(self, samples)
                with self._decode_lock:
                    stream = self._recognizer.create_stream()
                    stream.accept_waveform(SAMPLE_RATE, samples2)
                    self._recognizer.decode_stream(stream)
                    text = stream.result.text.strip()
                if _is_real_speech(text):
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
        self._theme = "green"  # 配色主题
        self._engine_type = "onnx"  # 识别引擎：onnx 离线 / edge 在线
        self._font_size = 10
        self._vad_threshold = 0.02  # 音量阈值（RMS）
        self._enable_denoiser = False  # 识别前降噪（GTCRN）
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
        self._entrance_pending = True  # 首次 show 时播放入场动画
        self._geo_pending = True  # 首次 show 时恢复窗口几何
        self._saved_win_geo = None
        self._saved_win_maxed = False
        self._float_geo = None  # 悬浮翻译窗位置
        self._speaker_device_name = ""  # 上次选择的捕获设备名
        self._speaker_beta_hint_off = False  # BETA 提示"不再提示"
        self._speaker_on = False
        self._close_to_tray = False  # 关闭时最小化到托盘
        self._force_quit = False    # 托盘"退出"真正退出标志
        self._autostart = False     # 开机自启
        self._tray = None

        self.sendFinished.connect(self._on_send_finished)
        self.translateFinished.connect(self._on_translate_finished)
        self._create_widgets()
        self._load_config()
        # 非默认主题：加载后立即应用（_apply_font_size 会用主题样式表）
        if self._theme != "green":
            self._apply_theme(self._theme)
        self._apply_layout()

        self.voice.partialResult.connect(self._on_partial)
        self.voice.finalResult.connect(self._on_final)
        self.voice.status.connect(self.status_bar.showMessage)
        self.voice.error.connect(self._on_voice_error)
        self.voice.vadState.connect(self._on_vad_state)
        self.voice.pttFinished.connect(self._on_ptt_finished)

        self._load_history()
        self._populate_mics()
        # 同步识别引擎下拉到配置值
        for i in range(self.engine_combo.count()):
            if self.engine_combo.itemData(i) == self._engine_type:
                self.engine_combo.blockSignals(True)
                self.engine_combo.setCurrentIndex(i)
                self.engine_combo.blockSignals(False)
                break
        self._connect_osc()
        self._update_char_count()
        self._apply_font_size()
        self.voice.set_engine_type(self._engine_type)
        self._apply_vad_params_to_engine()

        # 恢复上次窗口位置/大小（夹到可用屏幕范围内）
        geo = getattr(self, "_saved_window_geo", None)
        if geo and len(geo) == 4:
            x, y, w, h = map(int, geo)
            screen = QApplication.desktop().availableGeometry(self)
            x = max(screen.left(), min(x, screen.right() - 200))
            y = max(screen.top(), min(y, screen.bottom() - 200))
            w = min(w, screen.width())
            h = min(h, screen.height())
            self.setGeometry(x, y, w, h)

        # 无边框窗口的边缘缩放手势（应用级事件过滤器）
        self._resizer = FramelessResizer(self)
        # 下拉弹层：透明四角 + 去黑边/闪现
        self._polish_combo_popups()
        # 系统托盘
        self._setup_tray()
        # 静默检查更新（延迟，避免拖慢启动）
        QTimer.singleShot(4000, self._check_for_update)

    # ----------------------------------------------------------
    # 创建所有控件（不组装布局）
    # ----------------------------------------------------------
    def _create_widgets(self):
        self.setWindowTitle(f"{APP_TITLE}  v{APP_VERSION}")
        self.setMinimumSize(720, 600)

        # 自绘标题栏：去掉系统原生边框（用户觉得系统按钮难看），
        # 拖拽/缩放/最大化由 TitleBar + FramelessResizer 实现
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        # 设置窗口图标
        icon_path = os.path.join(RES_DIR, "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(APP_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 窗口标识 (不使用透明背景，避免文字溢出)
        self.setObjectName("mainWindow")

        # ---- 自绘标题栏 ----
        self.title_bar = TitleBar(self)

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
        self.translate_lang_combo = AnimatedComboBox()
        for label, code in TRANSLATE_LANGS:
            self.translate_lang_combo.addItem(label, code)
        self.translate_lang_combo.setCurrentIndex(0)  # 默认英语
        self.translate_lang_combo.currentIndexChanged.connect(lambda: self._save_config())
        trans_row.addWidget(self.translate_lang_combo)
        trans_row.addSpacing(8)
        trans_row.addWidget(QLabel("显示:"))
        self.translate_mode_combo = AnimatedComboBox()
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
        self.mic_combo = AnimatedComboBox()
        self.mic_combo.setMinimumWidth(120)
        settings_row.addWidget(self.mic_combo, stretch=1)
        settings_row.addSpacing(6)
        settings_row.addWidget(QLabel("语言:"))
        self.lang_combo = AnimatedComboBox()
        for label, code in LANGUAGES:
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(1)  # 默认中文
        # 连续监听运行中切换语言 → 识别器即时重建，无需重启监听
        self.lang_combo.currentIndexChanged.connect(
            lambda: (self.voice.set_language(self.lang_combo.currentData() or "zh"),
                     self._save_config()))
        settings_row.addWidget(self.lang_combo)
        settings_row.addSpacing(6)
        settings_row.addWidget(QLabel("引擎:"))
        self.engine_combo = AnimatedComboBox()
        self.engine_combo.addItem("离线 SenseVoice", "onnx")
        self.engine_combo.addItem("Edge 在线", "edge")
        self.engine_combo.setToolTip("离线识别不用联网；Edge 在线识别用微软云（中文效果更好，需联网）")
        self.engine_combo.currentIndexChanged.connect(
            lambda: (self.voice.set_engine_type(self.engine_combo.currentData() or "onnx"),
                     self._save_config()))
        settings_row.addWidget(self.engine_combo)
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

        # 悬浮翻译：捕获扬声器声音 → 识别 → 翻译 → 悬浮窗
        self.speaker_btn = QPushButton("🖥  悬浮翻译 BETA")
        self.speaker_btn.setObjectName("speakerBtn")
        self.speaker_btn.setCursor(Qt.PointingHandCursor)
        self.speaker_btn.setToolTip("捕获扬声器播放的语音，识别并翻译，结果显示在悬浮窗")
        self.speaker_btn.clicked.connect(self._toggle_speaker)
        voice_btn_row.addWidget(self.speaker_btn)

        voice_btn_row.addStretch()
        voice_layout.addLayout(voice_btn_row)

        # 第二行：音量条 + 降噪 + 状态（避免竖屏按钮行过宽截断）
        voice_opts_row = QHBoxLayout()
        self.mic_meter = MicLevelBar()
        self.mic_meter.setFixedWidth(150)
        self.mic_meter._keep_visible = True
        self.mic_meter.setVisible(True)
        self.mic_meter.set_threshold(self._vad_threshold)
        self.mic_meter.thresholdChanged.connect(self._on_min_rms_changed)
        voice_opts_row.addWidget(self.mic_meter)
        voice_opts_row.addSpacing(8)

        # 识别前降噪（GTCRN）：主页快捷开关，默认开启
        self.denoiser_home_chk = QCheckBox("识别前降噪")
        self.denoiser_home_chk.setChecked(self._enable_denoiser)
        self.denoiser_home_chk.setToolTip("识别前用 GTCRN 降噪，嘈杂环境更稳；高保真录音可关闭")
        self.denoiser_home_chk.stateChanged.connect(self._on_home_denoiser_toggled)
        voice_opts_row.addWidget(self.denoiser_home_chk)
        voice_opts_row.addStretch()

        self.vad_label = QLabel("")
        self.vad_label.setObjectName("dimLabel")
        voice_opts_row.addWidget(self.vad_label, 1)
        voice_layout.addLayout(voice_opts_row)

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
        # 长条目自动换行（避免被裁剪），像素级滚动，宽度变化时重算行高
        self.history_list.setItemDelegate(HistoryListDelegate(self.history_list, max_lines=4))
        self.history_list.setWordWrap(True)
        self.history_list.setUniformItemSizes(False)
        self.history_list.setResizeMode(QListView.Adjust)
        self.history_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.history_list.viewport().installEventFilter(self)
        self.history_list.itemDoubleClicked.connect(self._on_history_double_click)
        hist_layout.addWidget(self.history_list)

        # ---- 状态栏 ----
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        self.text_input.installEventFilter(self)

        # ---- 悬浮翻译：引擎 + 悬浮窗（隐藏，由按钮开关）----
        self._speaker_on = False
        self.float_win = FloatingTranslateWindow()
        self.speaker_engine = SpeakerEngine(self.translator)
        self.speaker_engine.partialResult.connect(self.float_add_pending)
        self.speaker_engine.translated.connect(self.float_add_pair)
        self.speaker_engine.status.connect(self.status_bar.showMessage)
        self.speaker_engine.status.connect(self.float_win.set_float_status)
        self.speaker_engine.error.connect(self._on_speaker_error)
        self.speaker_engine.finishedSig.connect(self._on_speaker_finished)
        self.float_win.source_combo.currentIndexChanged.connect(self._on_float_langs_changed)
        self.float_win.target_combo.currentIndexChanged.connect(self._on_float_langs_changed)
        self.float_win.device_combo.currentIndexChanged.connect(self._on_float_device_changed)
        self.float_win.closedByUser.connect(self._on_float_closed)
        self.float_win.pauseToggled.connect(self._on_float_pause)

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

        # 布局切换（设置里改横竖屏）时重播一次卡片入场，作为应用反馈
        if self.isVisible():
            QTimer.singleShot(0, self._play_card_entrance)

    def _build_portrait(self):
        """竖屏：Bento Grid 单列。"""
        self.resize(840, 880)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)
        outer_lay.addWidget(self.title_bar)
        outer_lay.addWidget(scroll, 1)
        self.setCentralWidget(outer)
        self._scroll = scroll

        central = QWidget()
        scroll.setWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(24, 8, 24, 16)
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
        self.resize(1160, 820)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(0)

        # 左侧面板
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_widget = QWidget()
        left_scroll.setWidget(left_widget)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(24, 8, 8, 16)
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
        right_layout.setContentsMargins(8, 8, 24, 16)
        right_layout.setSpacing(16)
        right_layout.addWidget(self.hist_group)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)  # 左 3
        splitter.setStretchFactor(1, 1)  # 右 1
        splitter.setSizes([800, 360])

        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)
        outer_lay.addWidget(self.title_bar)
        outer_lay.addWidget(splitter, 1)
        self.setCentralWidget(outer)
        self._main_container = splitter

    def _apply_theme(self, theme_id):
        """切换配色主题：重建样式表、刷新弹层视图样式、重绘极光。"""
        global STYLE_SHEET, POPUP_VIEW_QSS_THEMED
        STYLE_SHEET, POPUP_VIEW_QSS_THEMED = apply_theme(theme_id)
        self._theme = CURRENT_THEME
        # 刷新弹层视图的专属样式
        for combo in self.findChildren(QComboBox) + self.float_win.findChildren(QComboBox):
            try:
                combo.view().setStyleSheet(POPUP_VIEW_QSS_THEMED)
            except Exception:
                pass
        # 重建全局样式（含字体大小）并重绘极光
        self._apply_font_size()
        self.update()

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

    def _on_home_denoiser_toggled(self, state):
        self._enable_denoiser = bool(state)
        self._apply_vad_params_to_engine()
        self._save_config()

    def _on_min_rms_changed(self, rms):
        self._vad_threshold = float(rms)
        self._apply_vad_params_to_engine()
        self._save_config()

    def _apply_vad_params_to_engine(self):
        self.voice.set_vad_params(
            threshold=self._vad_threshold,
            min_silence=self._min_silence_duration,
            min_speech=self._min_speech_duration,
        )
        # 降噪开关同步到两个引擎
        self.voice._enable_denoiser = self._enable_denoiser
        # 悬浮翻译引擎同步音量阈值
        if hasattr(self, "speaker_engine"):
            self.speaker_engine._min_rms = self._vad_threshold
            self.speaker_engine._enable_denoiser = self._enable_denoiser

    def eventFilter(self, obj, event):
        if obj is self.text_input and event.type() == event.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and \
               event.modifiers() & Qt.ControlModifier:
                self._send()
                return True
        if isinstance(obj, QGroupBox) and self.isAncestorOf(obj):
            if event.type() == QEvent.Enter:
                self._animate_card_lift(obj, True)
            elif event.type() == QEvent.Leave:
                self._animate_card_lift(obj, False)
            return False
        if obj is self.history_list.viewport() and event.type() == event.Resize:
            # 列表宽度变化 → 换行后的条目高度需要重算。
            # 高度没变跳过；且必须延迟到事件循环外（在布局事件里直接 dataChanged 会重入崩溃）
            w = event.size().width()
            if w != getattr(self, "_hist_last_width", None):
                self._hist_last_width = w
                QTimer.singleShot(0, self._refresh_history_hints)
        return super().eventFilter(obj, event)

    def _refresh_history_hints(self):
        # 注意：不能在这里对 model 发 dataChanged(SizeHintRole)——
        # 绘制阶段重入模型更新会原生崩溃，必须走视图的公开重排版接口
        self.history_list.doItemsLayout()

    def paintEvent(self, event):
        """淡绿色极光背景：先让 QSS 画底色，再叠极光（顺序反了会被底色盖住）。"""
        super().paintEvent(event)
        paint_aurora_background(self, event)
        # 无边框窗口补一圈淡描边，浅色桌面上界定边界
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ar, ag, ab = CURRENT_ACCENT_RGB
        p.setPen(QColor(ar, ag, ab, 45))
        p.setBrush(Qt.NoBrush)
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def resizeEvent(self, event):
        """窗口大小变化时重绘背景。"""
        super().resizeEvent(event)
        self.update()

    def toggle_maximize(self):
        """无边框窗口的自定义最大化：还原到之前的几何，最大化不超过任务栏。"""
        if getattr(self, "_maxed", False):
            self._maxed = False
            geo = getattr(self, "_restore_geo", None)
            if geo is None:
                geo = QRect(120, 90, 1160, 820)
            self.setGeometry(geo)
        else:
            self._restore_geo = QRect(self.geometry())
            screen = QApplication.desktop().availableGeometry(self)
            self.setGeometry(screen)
            self._maxed = True
        self.title_bar.max_btn.setText("\u2750" if self._maxed else "\u25A1")

    def _apply_round_corners(self):
        """Win11: 让无边框窗口享受系统圆角（Win10 上无此 API，静默跳过）。"""
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), 4
            )
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_round_corners()
        # 恢复上次窗口位置/大小（仅首次显示）
        if getattr(self, "_geo_pending", True):
            self._geo_pending = False
            saved = getattr(self, "_saved_win_geo", None)
            if saved and len(saved) == 4:
                x, y, w, h = saved
                if w >= self.minimumWidth() and h >= self.minimumHeight():
                    self.setGeometry(x, y, w, h)
        # 首次显示：窗口淡入 + 上浮，卡片 50ms 间隔依次淡入（启动属罕见时刻）
        if getattr(self, "_entrance_pending", False):
            self._entrance_pending = False
            rise_fade_in(self, duration=220, rise=12)
            QTimer.singleShot(int(80 * MOTION_SCALE), self._play_card_entrance)
            if getattr(self, "_saved_win_maxed", False):
                QTimer.singleShot(int(350 * MOTION_SCALE), self.toggle_maximize)

    def _entrance_widgets(self):
        """参与入场动画的顶层卡片（两种布局共用同一批控件）。"""
        return [
            self.title_widget, self.subtitle_label, self.conn_group,
            self.msg_group, self.btn_widget, self.voice_group, self.hist_group,
        ]

    def _play_card_entrance(self):
        """卡片级联入场：淡入 + 14px 上浮归位（50ms 间隔重叠展开）。"""
        widgets = self._entrance_widgets()
        step = int(50 * MOTION_SCALE)
        for i, w in enumerate(widgets):
            try:
                fade_in(w, duration=280, delay=i * step)
            except RuntimeError:
                continue

        total = int((step * len(widgets) + 320 + 120) * MOTION_SCALE)
        # 入场用的透明度特效会顶掉阴影特效，入场结束后统一补挂玻璃阴影
        QTimer.singleShot(total, self._apply_glass_shadows)


    def _apply_glass_shadows(self):
        """给玻璃卡片挂悬浮阴影，并安装 hover 浮起动效过滤。"""
        for group in self.findChildren(QGroupBox):
            effect = group.graphicsEffect()
            if not isinstance(effect, QGraphicsDropShadowEffect):
                effect = QGraphicsDropShadowEffect(self)
                effect.setBlurRadius(16)
                effect.setOffset(0, 5)
                effect.setColor(QColor(20, 80, 40, 42))
                group.setGraphicsEffect(effect)
                group.installEventFilter(self)
        for group in self.float_win.findChildren(QGroupBox):
            pass  # 悬浮窗卡片尺寸贴合窗口，阴影会被裁剪，跳过

    def _animate_card_lift(self, obj, enter):
        """hover 时阴影扩散产生卡片浮起感（180ms OutCubic）。"""
        effect = obj.graphicsEffect()
        if not isinstance(effect, QGraphicsDropShadowEffect) or not MOTION_OK:
            return
        for prop, target in (
            ("blurRadius", 28 if enter else 16),
            ("yOffset", 10 if enter else 5),
        ):
            anim = QPropertyAnimation(effect, prop.encode("ascii"), obj)
            anim.setDuration(int(180 * MOTION_SCALE))
            anim.setEndValue(target)
            anim.setEasingCurve(_out_cubic())
            anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _setup_tray(self):
        """系统托盘：双击显示主窗口，右键菜单显示/退出。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon_path = os.path.join(RES_DIR, "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(APP_DIR, "app_icon.ico")
        menu = QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self._quit_from_tray)
        self._tray = QSystemTrayIcon(
            QIcon(icon_path) if os.path.exists(icon_path) else QIcon(), self)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip(APP_TITLE)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._force_quit = True
        self.close()

    @staticmethod
    def set_autostart(enabled):
        """开机自启：写/删 HKCU 启动项（仅打包版有效，源码运行无意义）。"""
        if not getattr(sys, "frozen", False):
            return
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            if enabled:
                winreg.SetValueEx(key, "VRChatOSCChatbox", 0, winreg.REG_SZ,
                                  '"{}"'.format(sys.executable))
            else:
                try:
                    winreg.DeleteValue(key, "VRChatOSCChatbox")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    @staticmethod
    def set_filter_fillers(enabled):
        """纯语气词过滤开关：影响 _is_real_speech 的分级判定。"""
        global FILTER_FILLERS
        FILTER_FILLERS = bool(enabled)

    def _check_for_update(self):
        """启动后静默检查 GitHub 最新版，有新版本在状态栏提示。"""
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/Txaniag/VRChat-OSC-Chatbox/releases/latest",
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest_tag = data.get("tag_name", "")
            if not latest_tag or not latest_tag.startswith("v"):
                return
            cur = APP_VERSION.split(".")
            latest = latest_tag.lstrip("v").split(".")
            if tuple(map(int, latest)) > tuple(map(int, cur)):
                self.status_bar.showMessage(
                    f"发现新版本 {latest_tag}，点击设置打开下载页")
                # 更新托盘菜单：加"打开最新版下载页"
                if self._tray is not None:
                    act = self._tray.contextMenu().addAction("打开最新版下载页")
                    act.triggered.connect(
                        lambda: webbrowser.open(
                            "https://github.com/Txaniag/VRChat-OSC-Chatbox/releases/latest"))
        except Exception:
            pass  # 网络失败静默

    def _polish_combo_popups(self):
        """下拉弹层：四角真正透明 + 去黑边/闪现（恢复 v4.1 UI overhaul 的处理）。"""
        for combo in self.findChildren(QComboBox) + self.float_win.findChildren(QComboBox):
            view = combo.view()
            if view is None:
                continue
            container = view.window()
            if container is None:
                continue
            try:
                # 弹层视图挂专用样式：透明容器下圆角/选中样式稳定生效
                view.setStyleSheet(POPUP_VIEW_QSS_THEMED)
                # 隐藏弹层滚动条（滚轮仍可滚动），避免突兀
                view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                # 容器四角透明：圆角由视图 QSS 绘制，四角露出下方内容而非黑色
                container.setAttribute(Qt.WA_TranslucentBackground)
                container.setWindowFlags(
                    Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
                )
                self._disable_native_frame_rendering(container)
            except Exception:
                pass

    @staticmethod
    def _disable_native_frame_rendering(container):
        """禁用 DWM 对弹窗的原生边框渲染并关闭系统过渡动画，避免打开瞬间闪黑。"""
        if sys.platform != "win32":
            return
        try:
            hwnd = int(container.winId())
            dwm = ctypes.windll.dwmapi
            val = ctypes.c_int(1)  # DWMNCRP_DISABLED
            dwm.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(val), ctypes.sizeof(val))
            none_color = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(none_color), ctypes.sizeof(none_color))
            trans = ctypes.c_int(1)  # DWMWA_TRANSITIONS_FORCEDISABLED
            dwm.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(trans), ctypes.sizeof(trans))
        except Exception:
            pass

    # ----------------------------------------------------------
    # 设置对话框
    # ----------------------------------------------------------
    def _open_settings(self):
        cfg = self._get_current_config()
        dlg = SettingsDialog(cfg, self)
        # 对话框里的下拉框也套弹层美化（透明四角/去黑边）
        self._polish_combo_popups()
        if dlg.exec_() == QDialog.Accepted:
            new_cfg = dlg.get_config()
            old_mode = self._layout_mode
            self._layout_mode = new_cfg.get("layout_mode", "portrait")
            self._font_size = new_cfg.get("font_size", 10)
            self._vad_threshold = new_cfg.get("vad_threshold", 0.02)
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
            # 行为设置：开机自启 + 关闭到托盘
            self._autostart = bool(new_cfg.get("autostart", False))
            self._close_to_tray = bool(new_cfg.get("close_to_tray", False))
            self.set_autostart(self._autostart)
            # 纯语气词过滤开关（模块级变量，影响识别结果分级）
            self.set_filter_fillers(bool(new_cfg.get("filter_fillers", True)))
            # 识别引擎切换（下次启动识别时生效）
            self._engine_type = new_cfg.get("engine_type", "onnx")
            self.voice.set_engine_type(self._engine_type)
            # 降噪开关
            self._enable_denoiser = bool(new_cfg.get("enable_denoiser", True))
            if hasattr(self, "denoiser_home_chk"):
                self.denoiser_home_chk.blockSignals(True)
                self.denoiser_home_chk.setChecked(self._enable_denoiser)
                self.denoiser_home_chk.blockSignals(False)
            # 配色主题
            new_theme = new_cfg.get("theme", "green")
            if new_theme != self._theme:
                self._apply_theme(new_theme)

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
        # 主窗口几何（最大化时保存还原矩形）
        if getattr(self, "_maxed", False):
            geo = getattr(self, "_restore_geo", None) or self.geometry()
        else:
            geo = self.geometry()
        return {
            "win_geo": [geo.x(), geo.y(), geo.width(), geo.height()],
            "win_maxed": bool(getattr(self, "_maxed", False)),
            "layout_mode": self._layout_mode,
            "theme": getattr(self, "_theme", "green"),
            "font_size": self._font_size,
            "vad_threshold": self._vad_threshold,
            "min_silence_duration": self._min_silence_duration,
            "min_speech_duration": self._min_speech_duration,
            "max_chars": self._max_chars,
            "translate_enabled": self.translate_chk.isChecked(),
            "translate_target": self.translate_lang_combo.currentData() or "en",
            "translate_mode": self.translate_mode_combo.currentData() or "bilingual",
            "baidu_appid": self.translator._baidu_appid,
            "baidu_secret": _obfuscate_secret(self.translator._baidu_secret),
            "autostart": bool(getattr(self, "_autostart", False)),
            "close_to_tray": bool(getattr(self, "_close_to_tray", False)),
            "enable_denoiser": bool(getattr(self, "_enable_denoiser", False)),
            "engine_type": getattr(self, "_engine_type", "onnx"),
            "speaker_source": self.float_win.source_lang(),
            "speaker_target": self.float_win.target_lang(),
            # 设备下拉未填充（如启动早期）时保留已保存的设备名，避免覆盖丢失
            "speaker_device": self.float_win.current_device_name() or getattr(self, "_speaker_device_name", ""),
            "speaker_beta_hint_off": getattr(self, "_speaker_beta_hint_off", False),
            "close_to_tray": getattr(self, "_close_to_tray", False),
            "autostart": getattr(self, "_autostart", False),
            "float_geo": self.float_win.save_geo(),
            "window_geo": [self.x(), self.y(), self.width(), self.height()],
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

    def _btn_swap_beat(self, btn):
        """状态切换（换 objectName）后的 160ms 渐显过渡拍，替代硬切。"""
        if not MOTION_OK:
            return
        try:
            effect = QGraphicsOpacityEffect(btn)
            effect.setOpacity(0.45)
            btn.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", btn)
            anim.setDuration(int(160 * MOTION_SCALE))
            anim.setStartValue(0.45)
            anim.setEndValue(1.0)
            anim.setEasingCurve(_out_cubic())

            def _cleanup():
                try:
                    if btn.graphicsEffect() is effect:
                        btn.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            anim.finished.connect(_cleanup)
            btn._swap_beat_anim = anim
            anim.start()
        except RuntimeError:
            pass

    # ----------------------------------------------------------
    # 发送
    # ----------------------------------------------------------
    @staticmethod
    def _voice_lang_to_baidu(lang_code):
        """将语音识别语言代码映射为百度翻译语言代码。"""
        return voice_lang_to_baidu(lang_code)

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
        target = QColor("#ff3b30" if length > limit else ("#ff9500" if length > limit * 0.8 else "#6b8f6b"))
        self.char_label.setText(f"{length} / {limit} 字符")
        self._animate_char_color(target)

    def _animate_char_color(self, target):
        """字数警示颜色 180ms 渐变过渡（绿→橙→红不再瞬切）。"""
        cur = getattr(self, "_char_color", None)
        if cur is None:
            cur = QColor("#6b8f6b")
        if cur == target:
            self.char_label.setStyleSheet(f"color: {target.name()};")
            return
        self._char_color = QColor(target)
        old = self.char_label
        anim = QVariantAnimation(self)
        anim.setDuration(int(180 * MOTION_SCALE))
        anim.setStartValue(QColor(cur))
        anim.setEndValue(QColor(target))
        anim.setEasingCurve(_out_cubic())
        label = self.char_label

        def _apply(val):
            try:
                c = QColor(val)
                label.setStyleSheet(f"color: {c.name()};")
            except RuntimeError:
                pass

        anim.valueChanged.connect(_apply)
        anim.start()
        self._char_color_anim = anim

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
        start_pulse(self.ptt_btn)  # 录音中呼吸脉冲，状态指示
        self.mic_meter.start(self.voice)  # 实时输入电平
        self.continuous_btn.setEnabled(False)
        self.mic_combo.setEnabled(False)
        self.lang_combo.setEnabled(False)
        hint = "正在录音... 再次点击停止并识别"
        if self.translate_chk.isChecked():
            hint += f"（翻译已开启，输出 {self.translate_lang_combo.currentText()}）"
        self.voice_hint.setText(hint)
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
        start_pulse(self.continuous_btn)  # 监听中呼吸脉冲，状态指示
        self.mic_meter.start(self.voice)  # 实时输入电平
        self.ptt_btn.setEnabled(False)
        self.mic_combo.setEnabled(False)
        self.lang_combo.setEnabled(False)
        hint = "连续监听中，说话后会自动识别"
        if self.translate_chk.isChecked():
            tgt = self.translate_lang_combo.currentText()
            hint += f"（翻译已开启，输出 {tgt}）"
        self.voice_hint.setText(hint)
        self.voice.start_continuous(
            device_index=self.mic_combo.currentData(),
            language=self.lang_combo.currentData() or "zh"
        )

    def _stop_continuous(self):
        self.voice.stop()
        self.continuous_btn.setEnabled(False)
        self.voice_hint.setText("正在停止...")

    # ----------------------------------------------------------
    # 悬浮翻译（回环捕获 → 识别 → 翻译 → 悬浮窗）
    # ----------------------------------------------------------
    def _enumerate_loopback_devices(self):
        """枚举所有输出设备的回环捕获项，默认输出的回环排首位。返回 [(显示名, 设备索引)]。"""
        if not _HAS_SPEAKER_LIB:
            return []
        items = []
        default_name = None
        try:
            p = pyaudio_wp.PyAudio()
            try:
                wasapi = p.get_host_api_info_by_type(pyaudio_wp.paWASAPI)
                out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                default_name = out.get("name", "")
                for lb in p.get_loopback_device_info_generator():
                    label = lb["name"].replace(" [Loopback]", "")
                    items.append((label, lb["index"]))
            finally:
                p.terminate()
        except Exception:
            return []
        # 去重（同名设备可能重复枚举），默认输出排最前
        seen = set()
        ordered = []
        for label, idx in items:
            if idx in seen:
                continue
            seen.add(idx)
            if default_name and default_name in label:
                ordered.insert(0, (label + "（默认）", idx))
            else:
                ordered.append((label, idx))
        return ordered

    def _toggle_speaker(self):
        if not self._speaker_on:
            if not _HAS_SPEAKER_LIB:
                QMessageBox.warning(
                    self, "缺少组件",
                    "缺少 pyaudiowpatch 库，无法捕获扬声器音频。\n请使用安装包重新安装本程序。"
                )
                return
            # BETA 功能首次使用前确认（可勾"不再提示"跳过）
            if not getattr(self, "_speaker_beta_hint_off", False):
                box = QMessageBox(self)
                box.setWindowTitle("悬浮翻译 BETA")
                box.setText(
                    "悬浮翻译目前是 BETA 功能，识别和翻译并不准确：\n\n"
                    "· 游戏/音乐等背景音会明显影响识别效果\n"
                    "· 识别结果可能有错字或缺词\n\n要继续吗？"
                )
                ok_btn = box.addButton("确定", QMessageBox.YesRole)
                back_btn = box.addButton("返回", QMessageBox.NoRole)
                dont_btn = box.addButton("不再提示", QMessageBox.ActionRole)
                box.setDefaultButton(ok_btn)
                box.exec_()
                clicked = box.clickedButton()
                if clicked is back_btn:
                    return
                if clicked is dont_btn:
                    self._speaker_beta_hint_off = True
                    self._save_config()
            devices = self._enumerate_loopback_devices()
            if not devices:
                QMessageBox.warning(
                    self, "悬浮翻译",
                    "没有找到可用的扬声器回环设备，无法捕获系统声音。"
                )
                return
            saved = getattr(self, "_speaker_device_name", "") or ""
            selected = None
            for label, idx in devices:
                if saved and saved in label:
                    selected = idx
                    break
            self.float_win.set_devices(devices, selected)
            device_index = self.float_win.current_device_index()
            self.float_win.clear_stream()
            self.float_win.set_float_status("正在启动...")
            self.float_win.show_at(getattr(self, "_float_geo", None))
            self.float_win.start_meter(self.speaker_engine)  # 捕获电平条
            source = self.float_win.source_lang()
            # 语言与麦克风识别器一致时借用（省一份模型内存），否则悬浮翻译自建
            shared = self.voice._recognizer if (
                self.voice._recognizer is not None
                and self.voice._language == source) else None
            self.speaker_engine.start(device_index, source,
                                      self.float_win.target_lang(), shared)
            self._speaker_on = True
            self._set_speaker_btn_active(True)
        else:
            self.speaker_engine.stop()
            self._on_speaker_finished()

    def _on_float_device_changed(self):
        """热切换捕获设备：重启捕获线程（悬浮窗保持显示）。"""
        self._save_config()
        if not self._speaker_on:
            return
        self.float_win.set_float_status("正在切换输出设备...")
        self.speaker_engine.stop()
        source = self.float_win.source_lang()
        shared = self.voice._recognizer if (
            self.voice._recognizer is not None
            and self.voice._language == source) else None
        self.speaker_engine.start(self.float_win.current_device_index(), source,
                                  self.float_win.target_lang(), shared)

    def _on_float_closed(self):
        """用户点悬浮窗 ✕：完全停止并复位主窗口按钮。"""
        if self._speaker_on:
            self.speaker_engine.stop()
            self._on_speaker_finished()

    def _on_float_pause(self, paused):
        """用户点 ⏸：暂停/继续捕获（音乐时暂停，不关翻译）。"""
        self.speaker_engine.set_paused(paused)
        if not paused and self.speaker_engine._segmenter is not None:
            # 恢复时清掉暂停前的残留分段状态，避免旧缓冲拼进新内容
            seg = self.speaker_engine._segmenter
            seg._seg_buf = []
            seg._preroll_buf.clear()
            seg.suppressed = False
            seg._quiet_run = 0.0

    def _set_speaker_btn_active(self, active):
        self.speaker_btn.setText("⏹  停止翻译" if active else "🖥  悬浮翻译 BETA")
        self.speaker_btn.setObjectName("speakerBtnActive" if active else "speakerBtn")
        self._repolish(self.speaker_btn)
        if not active:
            self._btn_swap_beat(self.speaker_btn)  # 恢复闲置态渐显过渡

    def _on_speaker_finished(self):
        # 引擎自然结束（错误/停止）时统一复位 UI
        if self._speaker_on:
            self._speaker_on = False
            self._set_speaker_btn_active(False)
            self.float_win.stop_meter()
            self.float_win.fade_hide()
            self.status_bar.showMessage("悬浮翻译已停止")

    def _on_speaker_error(self, msg):
        self.float_win.set_float_status(msg)
        if self._speaker_on:
            QMessageBox.warning(self, "悬浮翻译错误", msg)
        self._on_speaker_finished()

    def float_add_pending(self, text):
        if self._speaker_on:
            self.float_win.add_pending(text)

    def float_add_pair(self, original, translated):
        if self._speaker_on:
            self.float_win.add_pair(original, translated)

    def _on_float_langs_changed(self):
        if hasattr(self, "speaker_engine"):
            self.speaker_engine.set_langs(
                self.float_win.source_lang(), self.float_win.target_lang()
            )
        self._save_config()

    # ----------------------------------------------------------
    # 语音回调
    # ----------------------------------------------------------
    def _on_partial(self, text):
        was_empty = not self.partial_label.text()
        self.partial_label.setText(f"识别中: {text}")
        if was_empty and text:
            fade_in(self.partial_label, 150)

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
            if not self.vad_label.text() or is_fading_out(self.vad_label):
                self.vad_label.setText("🔊 检测到语音...")
                self.vad_label.setStyleSheet("color: #ff9500;")
                fade_in(self.vad_label, 150)
        else:
            if self.vad_label.text():
                # 出场更快（100ms），先淡出再清文字
                fade_out(self.vad_label, 100, finished=lambda: self.vad_label.setText(""))

    def _on_voice_error(self, msg):
        self.partial_label.setText("")
        self.vad_label.setText("")
        QMessageBox.warning(self, "语音识别错误", msg)
        # 错误路径没有"识别完成"状态消息跟进，主动刷新，避免状态栏停在"正在录音..."
        self.status_bar.showMessage("语音识别出错，请检查麦克风和模型")

    def _on_ptt_finished(self):
        was_ptt = self._is_ptt
        was_continuous = self._is_continuous
        self._is_ptt = False
        self._is_continuous = False
        self._hotkey_toggle_active = False
        self._update_hotkey_btn_visual(False)
        stop_pulse(self.ptt_btn)
        stop_pulse(self.continuous_btn)
        self.mic_meter.stop()

        self.ptt_btn.setText("🎤  按住说话")
        self.ptt_btn.setObjectName("micBtn")
        self._repolish(self.ptt_btn)
        self._btn_swap_beat(self.ptt_btn)
        self.ptt_btn.setEnabled(True)

        self.continuous_btn.setText("🔄  连续监听")
        self.continuous_btn.setObjectName("micContinuous")
        self._repolish(self.continuous_btn)
        self._btn_swap_beat(self.continuous_btn)
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
        item = QListWidgetItem(entry)
        item.setToolTip(entry)  # 悬停查看完整内容（换行最多 4 行，超出部分）
        self.history_list.insertItem(0, item)
        flash_history_item(item)  # 新条目绿色高亮淡出，作为发送成功反馈
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
                    # 过滤历史里纯语气词/纯符号的旧条目（规则变更前积累的垃圾）
                    content = item.split("] ", 1)[1] if "] " in item else item
                    if not _is_real_speech(content):
                        continue
                    list_item = QListWidgetItem(item)
                    list_item.setToolTip(item)
                    self.history_list.addItem(list_item)
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
                self._theme = cfg.get("theme", "green")
                self._font_size = cfg.get("font_size", 10)
                # 音量阈值（RMS）：旧版灵敏度值 0.1~0.9 迁移为 0.02
                _vt = cfg.get("vad_threshold", 0.02)
                self._vad_threshold = _vt if (isinstance(_vt, (int, float)) and 0 < _vt <= 0.15) else 0.02
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
                # 主窗口几何（showEvent 时应用，避免布局构建时被覆盖）
                self._saved_win_geo = cfg.get("win_geo", None)
                self._saved_win_maxed = bool(cfg.get("win_maxed", False))
                # 悬浮翻译窗设置（方向：其他语言 → 中文为默认）
                self.float_win.set_langs(
                    cfg.get("speaker_source", "zh"),
                    cfg.get("speaker_target", "zh"),
                )
                self._speaker_device_name = cfg.get("speaker_device", "")
                self._speaker_beta_hint_off = bool(cfg.get("speaker_beta_hint_off", False))
                self._close_to_tray = bool(cfg.get("close_to_tray", False))
                self._autostart = bool(cfg.get("autostart", False))
                self.set_filter_fillers(bool(cfg.get("filter_fillers", True)))
                self._engine_type = cfg.get("engine_type", "onnx")
                self._enable_denoiser = bool(cfg.get("enable_denoiser", True))
                self._float_geo = cfg.get("float_geo", None)
                self._saved_window_geo = cfg.get("window_geo", None)
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
            "theme": getattr(self, "_theme", "green"),
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
        # 关闭到托盘（设置里可开）：隐藏而不退出
        if getattr(self, "_close_to_tray", False) and not getattr(self, "_force_quit", False):
            self._save_config()
            self._save_history()
            self.osc.send_typing(False)
            self.hide()
            event.ignore()
            return
        if self._is_ptt or self._is_continuous:
            self.voice.stop()
        stop_pulse(self.ptt_btn)
        stop_pulse(self.continuous_btn)
        self.mic_meter.stop()
        self.speaker_engine.stop()
        self.float_win.close()
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
