; auto-workflow Inno Setup 安装脚本
; 编译：iscc setup.iss

#define MyAppName "auto-workflow"
#define MyAppVersion "0.1"
#define MyAppPublisher "LocalAI"
#define MyAppExeName "start-webui.bat"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=auto-workflow-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 代码文件
Source: "webui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "run.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "tasks.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "start-webui.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "workflows\*.yaml"; DestDir: "{app}\workflows"; Flags: ignoreversion
Source: "tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs
Source: "tests\*"; DestDir: "{app}\tests"; Flags: ignoreversion recursesubdirs
Source: "comfy\*"; DestDir: "{app}\comfy"; Flags: ignoreversion recursesubdirs

; Python 嵌入式环境由首次配置脚本自动下载

; 首次运行脚本
Source: "first-run\*"; DestDir: "{app}\first-run"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 首次运行：下载 ComfyUI 和模型
Filename: "{app}\first-run\setup.bat"; Description: "首次配置（下载 ComfyUI 和模型）"; Flags: nowait postinstall skipifsilent
; 启动 WebUI
Filename: "{app}\{#MyAppExeName}"; Description: "启动 auto-workflow"; Flags: nowait postinstall skipifsilent
