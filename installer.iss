#define MyAppName "AI TikTok LIVE Analyzer"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Shogo Yamashita"
#define MyAppExeName "AI-TikTok-LIVE-Analyzer.exe"

[Setup]
AppId={{C6153542-DD00-4AEA-B6A8-7F81031FB1E2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\AI TikTok LIVE Analyzer
DefaultGroupName={#MyAppName}

UninstallDisplayIcon={app}\{#MyAppExeName}

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

PrivilegesRequired=admin

OutputDir=D:\Projects\AI-TikTok-LIVE-Analyzer\installer_output
OutputBaseFilename=AI-TikTok-LIVE-Analyzer-Setup-1.0.0

SetupIconFile=D:\Projects\AI-TikTok-LIVE-Analyzer\AI_TikTok_LIVE_Analyzer.ico

Compression=lzma2
SolidCompression=yes

WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成"; GroupDescription: "追加アイコン:"; Flags: unchecked

[Files]
Source: "D:\Projects\AI-TikTok-LIVE-Analyzer\dist\AI-TikTok-LIVE-Analyzer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "AI TikTok LIVE Analyzerを起動"; Flags: nowait postinstall skipifsilent

