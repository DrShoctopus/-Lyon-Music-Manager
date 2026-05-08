; Inno Setup script for Lyon Music Manager
;
; Build with:
;   iscc.exe installer\lyon.iss
;
; Expects PyInstaller output already built at ..\dist\LyonMusicManager\.
; Produces installer\Output\LyonMusicManager-Setup.exe.

#define AppName       "Lyon Music Manager"
#define AppPublisher  "Lyon"
#define AppVersion    "0.1.0"
#define AppExe        "LyonMusicManager.exe"
#define AppId         "{{A8E1F8C5-7B3D-4E1F-9A4F-LYONMUSICMGR}}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=LyonMusicManager-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "associate";   Description: "Associate &FLAC files with {#AppName}"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
; Pull everything from the PyInstaller bundle.
Source: "..\dist\LyonMusicManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}";    Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";        Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Optional FLAC association
Root: HKCU; Subkey: "Software\Classes\.flac";                                      ValueType: string; ValueName: ""; ValueData: "LyonMusicManager.flac"; Tasks: associate; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\LyonMusicManager.flac";                      ValueType: string; ValueName: ""; ValueData: "FLAC Audio";              Tasks: associate; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\LyonMusicManager.flac\DefaultIcon";          ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0";        Tasks: associate
Root: HKCU; Subkey: "Software\Classes\LyonMusicManager.flac\shell\open\command";   ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
