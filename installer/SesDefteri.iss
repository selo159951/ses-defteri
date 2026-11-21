; Ses Defteri installer (Inno Setup 6). Built by build_windows.ps1:
;   ISCC /DSrc=..\dist\SesDefteri /DOutName=SesDefteri-Setup installer\SesDefteri.iss
; Installs for the current user only (no admin rights needed), adds Start menu and desktop shortcuts.
; Uninstalling keeps the user's recordings and models (%APPDATA%\SesDefteri).
#ifndef Src
  #define Src "..\dist\SesDefteri"
#endif
#ifndef OutName
  #define OutName "SesDefteri-Setup"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C1F7A52-3B1E-4E7B-9A55-5E5DEF7E1A01}
AppName=Ses Defteri
AppVersion={#AppVersion}
AppVerName=Ses Defteri {#AppVersion}
AppPublisher=Selim Oğuz
AppPublisherURL=https://github.com/selo159951/ses-defteri
DefaultDirName={localappdata}\Programs\Ses Defteri
DefaultGroupName=Ses Defteri
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename={#OutName}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\SesDefteri.exe
Compression=lzma2/normal
SolidCompression=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; app.py holds this mutex while running: a manual install asks to close the app first
AppMutex=SesDefteriMutex
CloseApplications=yes
SignedUninstaller=no

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Ses Defteri"; Filename: "{app}\SesDefteri.exe"
Name: "{group}\{cm:UninstallProgram,Ses Defteri}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Ses Defteri"; Filename: "{app}\SesDefteri.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SesDefteri.exe"; Description: "{cm:LaunchProgram,Ses Defteri}"; Flags: nowait postinstall skipifsilent
; after an in-app update (silent setup) the new version opens by itself
Filename: "{app}\SesDefteri.exe"; Flags: nowait; Check: WizardSilent

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
