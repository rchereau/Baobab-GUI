# make_shortcut.ps1 - creates "HPC Forest" shortcuts with the app icon
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
    # the app was called "Baobab HPC" before: remove that older shortcut
    Remove-Item -LiteralPath (Join-Path $dir 'Baobab HPC.lnk') -ErrorAction SilentlyContinue
    $lnk = $shell.CreateShortcut((Join-Path $dir 'HPC Forest.lnk'))
    $lnk.TargetPath = Join-Path $AppDir 'Baobab_Launcher.bat'
    $lnk.WorkingDirectory = $AppDir
    $lnk.IconLocation = (Join-Path $AppDir 'forest.ico') + ',0'
    $lnk.Description = 'Run jobs on the UNIGE HPC clusters'
    $lnk.Save()
}
