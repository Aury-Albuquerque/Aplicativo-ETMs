; Script do instalador do app de ETM da Grid Co.
; Compilar com: ISCC installer.iss

#define MyAppName "ETM Grid Co"
#define MyAppVersion "1.1.1"
#define MyAppPublisher "Grid Co."
#define MyAppExeName "ETM-GridCo.exe"

[Setup]
AppId={{8F2B9D7A-4C3E-4B1A-9E2F-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Instala por usuário por padrão -> não exige privilégio de administrador
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=ETM-GridCo-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; skipifsilent: instalações silenciosas (usadas pelo próprio app pra se
; auto-atualizar) NÃO reabrem o app sozinhas — o usuário reabre manualmente.
; Instalações manuais (duplo-clique no instalador) continuam oferecendo a
; opção de abrir na hora.
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent
