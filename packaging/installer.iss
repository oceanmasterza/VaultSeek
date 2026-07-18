; Inno Setup script for MusicVault (Windows installer).
;
; Produces a fully offline installer: the entire PyInstaller onedir
; (Python runtime, PySide6, fpcalc.exe, …) is copied under {app}.
;
; Prerequisites:
;   1. python packaging/fetch_vendor.py
;   2. pyinstaller packaging/musicvault.spec --noconfirm
;      (or: .\packaging\build_windows.ps1)
;   3. Install Inno Setup 6+
;   4. ISCC packaging\installer.iss
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
; Uninstall removes the whole onedir, including bundled fpcalc.exe
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Full onedir — includes MusicVault.exe, Python DLLs, Qt, fpcalc.exe, etc.
Source: "..\dist\MusicVault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not FileExists(ExpandConstant('{src}\..\dist\MusicVault\MusicVault.exe')) then
  begin
    MsgBox('dist\MusicVault\MusicVault.exe not found.'#13#10 +
           'Run packaging\build_windows.ps1 (or fetch_vendor + pyinstaller) first.',
           mbError, MB_OK);
    Result := False;
  end
  else if not FileExists(ExpandConstant('{src}\..\dist\MusicVault\fpcalc.exe')) then
  begin
    MsgBox('dist\MusicVault\fpcalc.exe is missing.'#13#10 +
           'Run: python packaging\fetch_vendor.py then rebuild with PyInstaller.',
           mbError, MB_OK);
    Result := False;
  end;
end;
