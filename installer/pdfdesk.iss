; Installs the folder build from dist\PDFDesk for the current user, and offers PDF Desk
; under Open With without taking over the default PDF app.
; Build with Inno Setup 6 after PyInstaller: ISCC installer\pdfdesk.iss
; Keep AppVersion in step with pdfdesk\__init__.py.

[Setup]
AppId={{6F3C2A51-8E4B-4C7D-9A10-2D5B7E91C3F4}
AppName=PDF Desk
AppVersion=0.1.0
DefaultDirName={autopf}\PDF Desk
DefaultGroupName=PDF Desk
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=PDFDesk-Setup-0.1.0
SetupIconFile=..\assets\pdfdesk.ico
UninstallDisplayName=PDF Desk
UninstallDisplayIcon={app}\PDFDesk.exe
Compression=lzma2
SolidCompression=yes
ChangesAssociations=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\PDFDesk\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\PDF Desk"; Filename: "{app}\PDFDesk.exe"; AppUserModelID: "PDFDesk.PDFDesk"

[Registry]
Root: HKA; Subkey: "Software\Classes\PDFDesk.pdf"; ValueType: string; ValueData: "PDF Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PDFDesk.pdf\DefaultIcon"; ValueType: string; ValueData: "{app}\PDFDesk.exe,0"
Root: HKA; Subkey: "Software\Classes\PDFDesk.pdf\shell\open\command"; ValueType: string; ValueData: """{app}\PDFDesk.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PDFDesk.pdf"; ValueData: ""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\PDFDesk.exe"; Description: "Open PDF Desk"; Flags: nowait postinstall skipifsilent

[Code]
// Settings, saved places and saved audio live outside the app folder. They're only removed if the
// person agrees, and a silent uninstall keeps them.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    Data := ExpandConstant('{userappdata}\PDFDesk');
    if DirExists(Data) and (MsgBox('Also delete your PDF Desk settings, list of recent files, saved reading places and saved audio?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(Data, True, True, True);
  end;
end;
