; Inno Setup Script for YouTube Downloader Windows Installer
; This script is processed by GitHub Actions to replace {{DIST_PATH}} with the actual path

[Setup]
AppName=YouTube Downloader
AppVersion=1.0.0
AppPublisher=YouTube Downloader
DefaultDirName={autopf}\YouTubeDownloader
DefaultGroupName=YouTube Downloader
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=YouTubeDownloader-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\YouTubeDownloader.exe
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{{DIST_PATH}}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\YouTube Downloader"; Filename: "{app}\YouTubeDownloader.exe"
Name: "{group}\Uninstall YouTube Downloader"; Filename: "{uninstallexe}"
Name: "{commondesktop}\YouTube Downloader"; Filename: "{app}\YouTubeDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\YouTubeDownloader.exe"; Description: "Launch YouTube Downloader"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
