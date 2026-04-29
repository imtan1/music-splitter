; ============================================================
; Inno Setup 安裝腳本 — 音樂分源程式
; 需要 Inno Setup 6.x：https://jrsoftware.org/isinfo.php
; ============================================================

#define AppName      "音樂分源程式"
#define AppNameEn    "MusicSplitter"
#define AppVersion   "1.1.0"
#define AppPublisher "MyStudio"
#define AppExeName   "MusicSplitter.exe"
#ifndef VersionSuffix
  #define VersionSuffix "CPU"
#endif

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\{#AppNameEn}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=
OutputDir=dist\installer
OutputBaseFilename=MusicSplitter_v{#AppVersion}_{#VersionSuffix}_Setup
SetupIconFile=
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
; 安裝完成後自動啟動
; PostInstallRun=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "額外工作："; Flags: unchecked
Name: "quicklaunchicon"; Description: "建立快速啟動捷徑"; GroupDescription: "額外工作："; Flags: unchecked

[Files]
; 主程式資料夾（PyInstaller 輸出）
Source: "dist\{#AppNameEn}\*"; \
  DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 開始功能表
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\解除安裝 {#AppName}"; Filename: "{uninstallexe}"
; 桌面捷徑
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
  Tasks: desktopicon
; 快速啟動
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; \
  Filename: "{app}\{#AppExeName}"; Tasks: quicklaunchicon

[Run]
; 安裝完成後可選擇立即開啟
Filename: "{app}\{#AppExeName}"; \
  Description: "立即啟動 {#AppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 解除安裝時刪除快取資料夾
Type: filesandordirs; Name: "{localappdata}\{#AppNameEn}"

[Code]
// 安裝前檢查是否已有舊版本
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

// 完成頁顯示提示
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 可在此執行安裝後動作
  end;
end;
