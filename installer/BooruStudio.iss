; Sprint 11 per-user installer. Building the capsule is deliberately a separate locked step.
[Setup]
AppName=Booru Studio
AppVersion=10.0.0
DefaultDirName={localappdata}\Programs\Booru Studio
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputBaseFilename=BooruStudioSetup

[Files]
Source: "..\dist\BooruStudio\*"; DestDir: "{app}\capsules\current"; Flags: recursesubdirs ignoreversion
Source: "..\dist\BooruStudioLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Booru Studio"; Filename: "{app}\BooruStudioLauncher.exe"
