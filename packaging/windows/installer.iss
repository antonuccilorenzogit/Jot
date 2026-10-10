; jot. — Inno Setup installer script
; Compiled by CI via: ISCC /DAppVersion=X.Y.Z installer.iss

#define AppName "jot"
#define AppExe "jot.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{F5364E93-8D78-4BD5-A376-7ACDF63C0AB7}
AppName={#AppName}
AppVerName={#AppName} v{#AppVersion}
AppVersion={#AppVersion}
AppPublisher=antonuccilorenzogit
AppPublisherURL=https://github.com/antonuccilorenzogit/Jot
AppSupportURL=https://github.com/antonuccilorenzogit/Jot/issues
AppUpdatesURL=https://github.com/antonuccilorenzogit/Jot/releases
DefaultDirName={userpf}\jot
DefaultGroupName=jot
SourceDir={#SourcePath}\..\..
OutputDir=dist
OutputBaseFilename=jot-Setup-v{#AppVersion}
SetupIconFile={#SourcePath}\..\..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName=jot
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Frictionless / Zero-Click Wizard configuration
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
ShowLanguageDialog=no
CloseApplications=force

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\jot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\jot"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\jot"; Filename: "{app}\{#AppExe}"

[Run]
Filename: "{app}\{#AppExe}"; Flags: nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
