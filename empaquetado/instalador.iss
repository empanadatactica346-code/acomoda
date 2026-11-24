; Instalador de Acomoda.  Compilar: ISCC empaquetado\instalador.iss  (después de pyinstaller)
[Setup]
AppName=Acomoda
AppVersion=3.2
AppPublisher=Acomoda
DefaultDirName={localappdata}\Programs\Acomoda
DefaultGroupName=Acomoda
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Instalar_Acomoda
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Acomoda.exe

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\Acomoda\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: "Acomoda_datos\*"

[Icons]
Name: "{group}\Acomoda"; Filename: "{app}\Acomoda.exe"
Name: "{group}\Desinstalar Acomoda"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Acomoda"; Filename: "{app}\Acomoda.exe"; Tasks: escritorio

[Run]
Filename: "{app}\Acomoda.exe"; Description: "Abrir Acomoda ahora"; Flags: nowait postinstall skipifsilent
