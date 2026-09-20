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
#define MyAppVersion "1.1.0"
#define MyAppPublisher "VaultSeek Contributors"
#define MyAppURL "https://github.com/oceanmasterza/VaultSeek"
#define MyAppExeName "VaultSeek.exe"

[Setup]
AppId={{A7C3E9F1-4B2D-4E8A-9C1F-6D5A8B7E0F32}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
; Prefer the previous install folder when upgrading the same AppId.
DefaultDirName={localappdata}\Programs\{#MyAppName}
UsePreviousAppDir=yes
DisableDirPage=auto
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=output
OutputBaseFilename=VaultSeek-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\src\vaultseek\gui\assets\vaultseek.ico
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Close VaultSeek before replacing files; continue if the user declines.
CloseApplications=yes
RestartApplications=no
; Same AppId + overwrite: install directly over an older VaultSeek.
; UninstallDisplayName appears in Settings → Apps.
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Checked by default on every install (Inno tasks are checked unless Flags: unchecked).
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Full onedir — embedded into Setup.exe at compile time (no build-tree needed at install).
; ISCC fails the build if Source paths are missing, so no runtime dist\ check is needed.
Source: "..\dist\VaultSeek\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Older builds bundled Poppler ICU, which shadows the Windows ICU required
; by Qt. Omitting it from the new payload does not remove it on upgrade.
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icudt78.dll"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\VaultSeek Help"; Filename: "{sys}\rundll32.exe"; Parameters: "url.dll,FileProtocolHandler ""{app}\help\HELP.html"""
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove leftover onedir files if any were created after install.
Type: filesandordirs; Name: "{app}"

