# VRChat OSC Chatbox

一个可以将语音识别和文字通过 OSC 协议发送到 VRChat 聊天框的桌面应用，支持离线语音识别和实时翻译。

## 功能特性

- 🎤 **离线语音识别**：使用 SenseVoice 本地模型，无需网络即可识别中文、英文、日语、韩语、粤语
- 🌐 **实时翻译**：支持百度翻译 API（需密钥）和 MyMemory 免费翻译
- 📱 **Apple 风格 UI**：淡绿色极光背景，Bento Grid 卡片式布局，圆角设计
- ⌨️ **全局热键**：自定义按键开始/停止语音识别
- 📝 **多语言显示**：双语/多语显示，支持 12 种目标语言
- 🔄 **横竖屏切换**：自适应布局，支持垂直/水平两种模式
- 🔌 **OSC 协议**：通过 OSC 发送文字到 VRChat 聊天框
- 💾 **配置持久化**：保存设置、历史记录和翻译配置

## 安装使用

### 1. 下载安装程序
- [VRChat_OSC_Chatbox_Setup_v4.exe](computer://d:\vrcosc1\VRChat_OSC_Chatbox_Setup_v4.exe)（238.7 MB）

### 2. 运行应用
- 双击安装程序，按向导完成安装
- 桌面会创建快捷方式
- 首次运行需要配置 OSC 端口和语音识别设置

### 3. 基本设置
- **OSC 设置**：填写 VRChat 的 OSC 端口（默认 9000）
- **语音识别**：选择语言模型和麦克风设备
- **翻译设置**（可选）：
  - 百度翻译：填入 AppID 和密钥（免费注册 fanyi-api.baidu.com）
  - 或使用 MyMemory 免费翻译

### 4. 使用方法
- **文字输入**：在文本框输入文字，点击发送
- **语音识别**：按住"按住说话"按钮或使用热键开始识别
- **自动发送**：勾选"连续监听"实现语音自动识别发送
- **翻译**：勾选翻译开关，选择目标语言，发送时自动翻译

## 技术栈

- **GUI 框架**：PyQt5
- **语音识别**：sherpa-onnx + SenseVoice 模型
- **翻译**：百度翻译 API / MyMemory API
- **网络协议**：python-osc（OSC 协议）
- **打包工具**：PyInstaller + Inno Setup
- **热键支持**：keyboard 库

## 文件结构

```
VRChat_OSC_Chatbox/
├── VRChat_OSC_Chatbox.exe           # 主程序
├── VRChat_OSC_Chatbox_Setup_v4.exe  # 安装程序
├── vrc_osc_chat.py                 # 主程序源码
├── requirements.txt                # 依赖包列表
├── installer.iss                   # Inno Setup 脚本
├── config.json                     # 用户配置
├── history.json                    # 历史记录
└── models/                         # 语音识别模型
    ├── sherpa-onnx-sense-voice-...
    └── silero_vad.onnx
```

## 开发说明

### 环境要求
- Python 3.8+
- Windows 10/11

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行开发版本
```bash
python vrc_osc_chat.py
```

### 打包命令
```bash
# 测试用单文件
python -m PyInstaller VRChat_OSC_Chatbox_onefile.spec --noconfirm

# 正式安装程序
python -m PyInstaller VRChat_OSC_Chatbox.spec --noconfirm
& 'C:\Program Files\Inno Setup 7\ISCC.exe' installer.iss
```

## 注意事项

1. **语音识别模型**：SenseVoice 模型约 228MB，首次运行会自动下载
2. **翻译 API**：百度翻译需要 AppID 和密钥，MyMemory 免费但可能有请求限制
3. **全局热键**：需要管理员权限运行
4. **OSC 端口**：确保 VRChat 已启用 OSC 并设置相同端口

## 许可证
MIT License

## 贡献
欢迎提交 Issue 和 Pull Request 来改进这个项目！