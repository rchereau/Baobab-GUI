# find_python.ps1 - locate a usable Python 3.9+ on this computer.
# Prints the path of the best 64-bit python.exe (nothing if none).
# Use -List to print every candidate with its version (diagnostics).
param([switch]$List)

$ErrorActionPreference = 'SilentlyContinue'
$candidates = New-Object System.Collections.Generic.List[string]

function Add-Candidate([string]$path) {
    if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
        $candidates.Add((Get-Item -LiteralPath $path).FullName)
    }
}

# 1. Registry (PEP 514): python.org, Anaconda, Miniconda, Store Python
foreach ($root in 'HKCU:\Software\Python', 'HKLM:\Software\Python',
                  'HKLM:\Software\WOW6432Node\Python') {
    foreach ($company in @(Get-ChildItem -LiteralPath $root)) {
        foreach ($tag in @(Get-ChildItem -LiteralPath $company.PSPath)) {
            $ip = Get-ItemProperty -LiteralPath (Join-Path $tag.PSPath 'InstallPath')
            if ($ip) {
                if ($ip.ExecutablePath) { Add-Candidate $ip.ExecutablePath }
                if ($ip.'(default)') { Add-Candidate (Join-Path $ip.'(default)' 'python.exe') }
            }
        }
    }
}

# 2. PATH and the py launcher's list
foreach ($cmd in @(Get-Command python.exe, python3.exe -All -CommandType Application)) {
    Add-Candidate $cmd.Source
}
if (Get-Command py.exe -CommandType Application) {
    foreach ($line in @(& py.exe -0p 2>$null)) {
        if ($line -match '([A-Za-z]:\\.*\.exe)\s*$') { Add-Candidate $Matches[1] }
    }
}

# 3. Conda installs and environments
if ($env:USERPROFILE) {
    $envs = Join-Path $env:USERPROFILE '.conda/environments.txt'
    foreach ($dir in @(Get-Content -LiteralPath $envs)) {
        if ($dir.Trim()) { Add-Candidate (Join-Path $dir.Trim() 'python.exe') }
    }
}

# 4. Usual install folders
$folders = @()
foreach ($base in @($env:LOCALAPPDATA, $env:USERPROFILE, $env:ProgramData, $env:ProgramFiles,
                    ${env:ProgramFiles(x86)}, 'C:\')) {
    if ($base -and (Test-Path -LiteralPath $base)) {
        foreach ($name in 'anaconda3', 'Anaconda3', 'miniconda3', 'Miniconda3', 'miniforge3',
                          'mambaforge', 'Programs/Python/Python3*', 'Python3*') {
            foreach ($d in @(Get-Item -Path (Join-Path $base $name))) { $folders += $d.FullName }
        }
    }
}
foreach ($d in $folders) { Add-Candidate (Join-Path $d 'python.exe') }

# Paths that are never a usable base interpreter
$exclude = '[\\/]Lib[\\/]venv[\\/]|[\\/]pkgs[\\/]|[\\/]site-packages[\\/]|[\\/]\.venv[\\/]|[\\/]Baobab GUI[\\/]'

function Test-Candidates {
    $found = @()
    foreach ($c in @($candidates | Select-Object -Unique)) {
        if ($c -match $exclude) { continue }
        $out = & $c -c "import sys,struct;print(sys.version_info[0],sys.version_info[1],sys.version_info[2],struct.calcsize(chr(80))*8)" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
        $p = "$out".Trim().Split(' ')
        if ($p.Count -lt 4) { continue }
        $ver = [version]("{0}.{1}.{2}" -f $p[0], $p[1], $p[2])
        if ($ver -lt [version]'3.9') { continue }
        if ($p[3] -ne '64') { continue }            # PySide6 needs 64-bit Python
        $isConda = Test-Path -LiteralPath (Join-Path (Split-Path $c) 'conda-meta')
        # prefer versions PySide6 surely supports, then python.org over conda, then newest
        $score = 0
        if ($ver -lt [version]'3.14') { $score += 100 }
        if (-not $isConda) { $score += 10 }
        $found += [pscustomobject]@{ Path = $c; Version = $ver; Conda = $isConda; Score = $score }
    }
    return $found
}

$found = @(Test-Candidates)

# 5. Last resort: shallow disk search of the usual places
if ($found.Count -eq 0) {
    foreach ($spec in @(@($env:LOCALAPPDATA, 4), @($env:USERPROFILE, 3), @($env:ProgramData, 3),
                        @($env:ProgramFiles, 3), @(${env:ProgramFiles(x86)}, 3))) {
        if ($spec[0] -and (Test-Path -LiteralPath $spec[0])) {
            foreach ($f in @(Get-ChildItem -LiteralPath $spec[0] -Filter python.exe -File -Recurse `
                                -Depth $spec[1] -Force)) {
                Add-Candidate $f.FullName
            }
        }
    }
    $found = @(Test-Candidates)
}

if ($List) {
    if ($found.Count -eq 0) { Write-Output '   (no working 64-bit Python 3.9+ found)' }
    foreach ($f in $found | Sort-Object Score, Version -Descending) {
        $kind = if ($f.Conda) { 'conda' } else { 'python.org/other' }
        Write-Output ("   {0,-8} {1,-17} {2}" -f $f.Version, $kind, $f.Path)
    }
    exit 0
}
$best = $found | Sort-Object Score, Version -Descending | Select-Object -First 1
if ($best) { Write-Output $best.Path; exit 0 }
exit 1
