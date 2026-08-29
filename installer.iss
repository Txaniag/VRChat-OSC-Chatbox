; ============================================================
; VRChat OSC Chatbox Sender - Inno Setup 安装脚本
; ============================================================

#define MyAppName "VRChat OSC Chatbox"
#define MyAppVersion "4.0.0"
#define MyAppPublisher "VRChat Tools"
#define MyAppExeName "VRChat_OSC_Chatbox.exe"
#define MyAppIcon "app_icon.ico"

[Setup]
AppId={{B8F3A2E1-7C4D-4E9F-A1B2-3D5E8F7C9A01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=VRChat_OSC_Chatbox_Setup_v4
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
SetupIconFile={#SourcePath}\app_icon.ico
DisableDirPage=no
DisableReadyPage=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "附加选项:"
Name: "runatstart"; Description: "开机自启动"; GroupDescription: "附加选项:"

[Files]
Source: "dist\VRChat_OSC_Chatbox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autostartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: runatstart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\config.json"
Type: filesandordirs; Name: "{app}\history.json"
Type: filesandordirs; Name: "{app}\sxw.txt"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
