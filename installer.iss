#define MyAppName "Livemetry Pulse"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "Shogo Yamashita"
#define MyAppExeName "LivemetryPulse.exe"

[Setup]
AppId={{C6153542-DD00-4AEA-B6A8-7F81031FB1E2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\Livemetry Pulse
DefaultGroupName={#MyAppName}

UninstallDisplayIcon={app}\{#MyAppExeName}

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

PrivilegesRequired=admin

OutputDir=D:\Projects\AI-TikTok-LIVE-Analyzer\installer_output
OutputBaseFilename=LivemetryPulse-Setup-v{#MyAppVersion}

SetupIconFile=D:\Projects\AI-TikTok-LIVE-Analyzer\LivemetryPulse.ico

Compression=lzma2
SolidCompression=yes

WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成"; GroupDescription: "追加アイコン:"; Flags: unchecked

[Files]
Source: "D:\Projects\AI-TikTok-LIVE-Analyzer\dist\LivemetryPulse\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Livemetry Pulseを起動"; Flags: nowait postinstall skipifsilent

