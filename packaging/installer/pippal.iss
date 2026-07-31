; Inno Setup script for PipPal (free edition) v0.3.3
; =====================================================================
; Prerequisites
; -----
; 1. PyInstaller must have already produced dist\PipPal\  (onedir).
;    Run from the repo root:  pyinstaller --noconfirm packaging\pippal.spec
; 2. Compile this script:     ISCC packaging\installer\pippal.iss
;    Output:                  dist\PipPal-Setup-0.3.3.exe
;
; WebView2 Runtime
; -----
; PipPal uses pywebview with the EdgeChromium (WebView2) backend.
; WebView2 ships pre-installed on:
;   * Windows 10 20H2 and later (KB5005563+)
;   * All Windows 11 editions
; For older Windows 10 builds, install the Evergreen Bootstrapper from:
;   https://developer.microsoft.com/en-us/microsoft-edge/webview2/
;
; The default voice is NOT bundled — PipPal downloads it on first run
; via the onboarding flow, keeping the installer small (~50–80 MB).
;
; App identity
; -----
; AppId GUID is fixed so Add/Remove Programs tracks upgrades correctly.
; Do NOT change it between releases.
; =====================================================================

#define MyAppName      "PipPal"
#define MyAppVersion   "0.3.3"
#define MyAppPublisher "Bug Factory"
#define MyAppURL       "https://pippal.bugfactory.hu"
#define MyAppExeName   "PipPal.exe"

[Setup]
; Fixed GUID — must not change between releases (upgrade detection).
AppId={{B7E3F2A1-4C9D-4E6B-8F0A-1D2E3C4B5A67}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; {autopf} resolves to Program Files when elevated, or
; {localappdata}\Programs when running without elevation —
; matching Softpedia / standard per-user install conventions.
DefaultDirName={autopf}\{#MyAppName}

; Allow the user to choose elevation at startup (shows a UAC dialog
; when they pick Program Files; silent if they pick LocalAppData).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

DisableProgramGroupPage=yes

; Output — goes to <repo root>\dist\ next to the PyInstaller bundle.
OutputDir=..\..\dist
OutputBaseFilename=PipPal-Setup-{#MyAppVersion}

SetupIconFile=..\..\assets\pippal_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; x64 only — matches the PyInstaller target_arch=x64 and piper.exe.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
  Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; \
  Flags: unchecked

[Files]
; Bundle the entire PyInstaller onedir output.
; Path is relative to the .iss file location (packaging\installer\).
Source: "..\..\dist\PipPal\*"; \
  DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut.
Name: "{autoprograms}\{#MyAppName}"; \
  Filename: "{app}\{#MyAppExeName}"; \
  IconFilename: "{app}\{#MyAppExeName}"

; Optional Desktop shortcut (unchecked by default — respects user choice).
Name: "{autodesktop}\{#MyAppName}"; \
  Filename: "{app}\{#MyAppExeName}"; \
  IconFilename: "{app}\{#MyAppExeName}"; \
  Tasks: desktopicon

[Run]
; Offer to launch PipPal after install (standard "Launch PipPal" checkbox).
Filename: "{app}\{#MyAppExeName}"; \
  Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Best-effort quit of any running instance before files are removed.
; PipPal has no --quit flag today; if the exe is absent we skip safely.
Filename: "taskkill.exe"; \
  Parameters: "/IM {#MyAppExeName} /F"; \
  Flags: runhidden skipifdoesntexist; \
  RunOnceId: "QuitPipPal"
