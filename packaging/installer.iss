; Inno Setup script for MusicVault (Windows installer).
;
; Prerequisites:
;   1. Build the onedir bundle: pyinstaller packaging/musicvault.spec --noconfirm
;   2. Install Inno Setup 6+
;   3. Compile this script (ISCC packaging\installer.iss)
;
; Output: packaging\output\MusicVault-Setup.exe

#define MyAppName "MusicVault"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "MusicVault Contributors"
#define MyAppURL "https://github.com/oceanmasterza/MusicVault"
#define MyAppExeName "MusicVault.exe"

[Setup]
AppId={{A7C3E9F1-4B2D-4E8A-9C1F-6D5A8B7E0F32}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=output
OutputBaseFilename=MusicVault-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\MusicVault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
