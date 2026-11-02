; packaging/installer.iss
; Inno Setup script - wraps the PyInstaller folder into Garud360LiVision-Setup.exe
#define MyAppName "Garud 360 Li-Vision"
#define MyAppVersion GetEnv("GARUD_VERSION")
#if MyAppVersion == ""
#define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{6E4A2F1B-7C3D-4B58-9A0E-5D1F0C9B2A74}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Garud
DefaultDirName={autopf}\Garud360LiVision
DefaultGroupName={#MyAppName}
OutputDir=..\Output
OutputBaseFilename=Garud360LiVision-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Garud360LiVision.exe
Compression=lzma2/fast
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Garud360LiVision\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Garud360LiVision.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\Garud360LiVision.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Garud360LiVision.exe"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent

; User data (database, snapshots, logs) lives in %LOCALAPPDATA%\Garud360LiVision and is intentionally kept on uninstall.
