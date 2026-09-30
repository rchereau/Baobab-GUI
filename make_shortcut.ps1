# make_shortcut.ps1 - creates "Baobab HPC" shortcuts with the app icon
# (a .bat file cannot carry its own icon). Called by Baobab_Launcher.bat.
param([Parameter(Mandatory = $true)][string]$AppDir)
$ErrorActionPreference = 'Stop'
$AppDir = (Resolve-Path -LiteralPath $AppDir).Path
$shell = New-Object -ComObject WScript.Shell
$places = @($AppDir,
            [Environment]::GetFolderPath('Desktop'),
            [Environment]::GetFolderPath('Programs'))      # Start menu
foreach ($dir in $places) {
    if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { continue }
    $lnk = $shell.CreateShortcut((Join-Path $dir 'Baobab HPC.lnk'))
    $lnk.TargetPath = Join-Path $AppDir 'Baobab_Launcher.bat'
    $lnk.WorkingDirectory = $AppDir
    $lnk.IconLocation = (Join-Path $AppDir 'baobab.ico') + ',0'
    $lnk.Description = 'Submit jobs to the UNIGE Baobab cluster'
    $lnk.Save()
}
