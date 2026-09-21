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
; 主程序与后台代理（--proxy）的检测与刹停由 [Code] 的 InitializeSetup/InitializeUninstall
; 完成（AppMutex 只能覆盖持互斥体的主程序，且只能让用户手动关闭，无法一键刹停）
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
const
  AppImageName = 'a4api.exe';

// 是否有 a4api.exe 在运行（主程序与后台代理共用同一可执行文件，一并覆盖）
function AppRunning(): Boolean;
var
  Rc: Integer;
begin
  Result := False;
  if Exec(ExpandConstant('{cmd}'),
          '/C tasklist /FI "IMAGENAME eq ' + AppImageName + '" 2>NUL | find /I "' + AppImageName + '" >NUL',
          '', SW_HIDE, ewWaitUntilTerminated, Rc) then
    Result := (Rc = 0);
end;

// 刹停全部相关服务：先优雅终止（给 SQLite 落盘留 3 秒），仍存活则强制结束，
// 之后最多再等 10 秒确认退出（优雅关闭可能因应用内未完成的网络请求而拖慢进程退出）。
function StopAllAppProcesses(): Boolean;
var
  Rc: Integer;
  I: Integer;
begin
  Result := True;
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM ' + AppImageName + ' >NUL 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, Rc);
  for I := 1 to 6 do
  begin
    if not AppRunning() then Exit;
    Sleep(500);
  end;
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM ' + AppImageName + ' >NUL 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, Rc);
  for I := 1 to 20 do
  begin
    if not AppRunning() then Exit;
    Sleep(500);
  end;
  Result := False;
end;

// 静默安装/卸载（如应用内更新触发）没有界面可点：AppRunning 时默认确认刹停；
// 交互安装则弹中文确认框，用户选「否」直接中止。
function ConfirmStopAndStop(): Boolean;
begin
  Result := True;
  if WizardSilent() then
    Exit;  // 静默：无需确认，交给下方 StopAllAppProcesses
  if MsgBox('检测到 a4api 正在运行（主界面或后台代理服务）。' #13#10 #13#10
            '是否关闭全部相关服务并继续？',
            mbConfirmation, MB_YESNO) = IDYES then
    Exit;
  Result := False;  // 用户选择不关闭 → 中止
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if AppRunning() then
  begin
    if ConfirmStopAndStop() then
    begin
      if not StopAllAppProcesses() then
      begin
        if not WizardSilent() then
          MsgBox('无法结束 a4api 进程，请手动关闭后重试安装。', mbCriticalError, MB_OK);
        Result := False;
      end;
    end
    else
      Result := False;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  if AppRunning() then
  begin
    if ConfirmStopAndStop() then
    begin
      if not StopAllAppProcesses() then
      begin
        if not WizardSilent() then
          MsgBox('无法结束 a4api 进程，请手动关闭后重试卸载。', mbCriticalError, MB_OK);
        Result := False;
      end;
    end
    else
      Result := False;
  end;
end;

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
