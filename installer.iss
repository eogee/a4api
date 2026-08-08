; a4api 每用户安装脚本（Inno Setup 6）
; 由 build.py --installer 编译，版本号通过 /DMyAppVersion 注入。
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "a4api"
#define MyAppExeName "a4api.exe"

[Setup]
AppId={{8A3C5F71-2B4D-4E6F-9A0B-1C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=a4api
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=a4api-setup-{#MyAppVersion}
SetupIconFile=resources\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; 与 desktop.py singleton.py 的单实例互斥体同名：GUI 运行时禁止安装/卸载覆盖
AppMutex=Local\A4ApiDesktopApp
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
; 安装向导默认英文（Default.isl 随 Inno 自带，保证构建可复现）。
; 如需中文向导，把社区翻译文件 ChineseSimplified.isl 放到 resources\inno\ 下
; （Inno 6 不自带该文件），此条件引用会自动生效。
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists("resources\inno\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "resources\inno\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "dist\a4api\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 后台翻译代理（--proxy 进程）不持 AppMutex，卸载前必须显式停掉并清理 proxy.json
Filename: "{app}\{#MyAppExeName}"; Parameters: "--proxy-stop"; Flags: runhidden

[UninstallDelete]
; 卸载后移除 {app} 空目录（unins000.exe 自删除时序可能导致目录移除被跳过）
Type: dirifempty; Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    // 升级/覆盖安装：先停旧代理、清掉旧 onedir 残留（_internal 中被删的 DLL 不会自动移除，
    // 且正在运行的代理会锁住 exe/DLL 导致拷贝失败），确保全新文件落盘。
    if FileExists(ExpandConstant('{app}\{#MyAppExeName}')) then
    begin
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--proxy-stop', '', SW_HIDE,
           ewWaitUntilTerminated, ErrorCode);
      DelTree(ExpandConstant('{app}\_internal'), True, True, True);
    end;
  end;
end;
