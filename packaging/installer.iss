; Inno Setup script for VaultSeek (Windows installer).
;
; Produces a fully offline installer: the entire PyInstaller onedir
; (Python runtime, PySide6, fpcalc.exe, …) is copied under {app}.
;
; Prerequisites:
;   1. python packaging/fetch_vendor.py
;   2. pyinstaller packaging/vaultseek.spec --noconfirm
;      (or: .\packaging\build_windows.ps1)
;   3. Install Inno Setup 6+
;   4. ISCC packaging\installer.iss
;
; Output: packaging\output\VaultSeek-Setup.exe

#define MyAppName "VaultSeek"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "VaultSeek Contributors"
#define MyAppURL "https://github.com/oceanmasterza/VaultSeek"
#define MyAppExeName "VaultSeek.exe"

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
OutputBaseFilename=VaultSeek-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Uninstall removes the whole onedir, including bundled fpcalc.exe
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Checked by default on every install (Inno tasks are checked unless Flags: unchecked).
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Full onedir — embedded into Setup.exe at compile time (no build-tree needed at install).
; ISCC fails the build if Source paths are missing, so no runtime dist\ check is needed.
Source: "..\dist\VaultSeek\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

