; Inno Setup script for ClipBot-Setup.exe; scripts/build_windows.ps1 compiles it after ClipBot.exe.
; Installs for the current user only (no administrator prompt). Uninstalling keeps the data folder
; and the keys in Windows Credential Manager, so reinstalling picks up where it left off.

#define AppVersion "0.1.0"

[Setup]
AppId={{8F3C2B61-5E0A-4D7B-9C41-2A6E0B7D4F19}
AppName=ClipBot
AppVersion={#AppVersion}
AppPublisher=ClipBot
DefaultDirName={localappdata}\Programs\ClipBot
DefaultGroupName=ClipBot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ClipBot-Setup
SetupIconFile=..\build\clipbot.ico
UninstallDisplayIcon={app}\ClipBot.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "startup"; Description: "Start ClipBot when I sign in to Windows (so scheduled posts go out)"

[Files]
Source: "..\dist\ClipBot\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\ClipBot"; Filename: "{app}\ClipBot.exe"
Name: "{userdesktop}\ClipBot"; Filename: "{app}\ClipBot.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ClipBot"; ValueData: """{app}\ClipBot.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\ClipBot.exe"; Description: "Open ClipBot now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/im ClipBot.exe /f"; Flags: runhidden; RunOnceId: "StopClipBot"
