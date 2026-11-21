; Ses Defteri (simple edition) installer (Inno Setup 6). Built by build_windows.ps1.
; Installs for the current user only (no admin rights needed), adds Start menu and desktop shortcuts.
; Uninstalling keeps the user's recordings and models (%APPDATA%\SesDefteriBasit).
#ifndef Src
  #define Src "..\dist\SesDefteri"
#endif
#ifndef OutName
  #define OutName "SesDefteri-Basit-Setup"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6268B6E2-114E-4972-B995-1EFBC7815E3E}
AppName=Ses Defteri
AppVersion={#AppVersion}
AppVerName=Ses Defteri {#AppVersion}
AppPublisher=Selim Oğuz
AppPublisherURL=https://github.com/selo159951/ses-defteri
DefaultDirName={localappdata}\Programs\Ses Defteri Basit
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
AppMutex=SesDefteriBasitMutex
CloseApplications=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\KULLANIM.txt"; DestDir: "{app}"; Flags: ignoreversion

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
