; Livemetry Pulse BETA installer (test distribution only).
; Separate from installer_release.iss in every identity that
; matters: a different AppId, install folder, executable name and
; start-menu group, so installing / uninstalling the beta NEVER
; touches the released v1.6.0 installation. App data is separated
; at runtime by the beta edition mechanism (core/app_edition.py):
; the beta stores everything under
;   %LOCALAPPDATA%\LivemetryPulseBeta\AI-TikTok-LIVE-Analyzer
; and uses a separate keyring service (…-Beta).
; MyAppVersion MUST match BETA_VERSION_LABEL in core/app_edition.py
; and ProductVersion in version_info_beta.txt (build_beta.bat
; verifies this and fails the build on a mismatch).

#define MyAppName "Livemetry Pulse Beta"
#define MyAppVersion "1.6.0-beta.1"
#define MyAppPublisher "Yamashita Shogo"
#define MyAppExeName "LivemetryPulseBeta.exe"

[Setup]
AppId={{5F1D4EC2-4F38-453F-BAB1-D1160BF2444C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Livemetry Pulse Beta
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=LivemetryPulseBeta-Setup-v{#MyAppVersion}
SetupIconFile=assets\LivemetryPulse.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
MinVersion=10.0.17763

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成"; GroupDescription: "追加アイコン:"; Flags: unchecked

[Files]
Source: "dist\LivemetryPulseBeta\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The edition marker also sits next to the exe itself (the spec
; bundles a copy inside _internal as well; either location works).
Source: "beta_edition.flag"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName}を起動"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
; NOTE: the beta DATA folder (%LOCALAPPDATA%\LivemetryPulseBeta) is
; intentionally NOT deleted on uninstall — it is test data the user
; may want to inspect. Delete it manually when it is no longer
; needed. The release build's data is never stored there.

