# Build the simple app: .\build_windows.ps1  ->  Desktop\Projeler\Ses Defteri\Basit Sürüm (setup, zip, folder)
# One package for every PC: runs on the processor, the speech model is downloaded on first start (internet once).
# Uses the Python environment of the full project next to it (..\Ana Sürüm\.venv).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot "..\Ana Sürüm\.venv\Scripts"
& "$py\python.exe" -m PyInstaller --noconfirm --clean SesDefteri.spec
# the Visual C++ runtime must be inside the package (a PC without the redistributable still has to work)
foreach ($d in "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "python312.dll") {
    if (-not (Test-Path "dist\SesDefteri\_internal\$d")) { throw "$d is missing from the package" }
}
# output: Desktop\Projeler\Ses Defteri\Basit Sürüm (setup, zip, and the unzipped folder)
$desk = [Environment]::GetFolderPath("Desktop")
$dest = Join-Path $desk "Projeler\Ses Defteri\Basit Sürüm"
New-Item -ItemType Directory -Force $dest | Out-Null
$stage = "dist\SesDefteri-Basit"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
Copy-Item -Recurse dist\SesDefteri $stage
Copy-Item KULLANIM.txt $stage  # the one-page guide next to the exe
if (Test-Path dist\SesDefteri-Basit.zip) { Remove-Item -Force dist\SesDefteri-Basit.zip }
Push-Location dist; & "$env:SystemRoot\System32	ar.exe" -a -c -f SesDefteri-Basit.zip SesDefteri-Basit; Pop-Location
$out = Join-Path $dest "SesDefteri-Basit (kurulumsuz)"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
Copy-Item -Recurse $stage $out
Copy-Item -Force dist\SesDefteri-Basit.zip $dest
# installer (Inno Setup 6): per-user, Start menu and desktop shortcut named "Ses Defteri"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q /DSrc=..\dist\SesDefteri installer\SesDefteri.iss
    Copy-Item -Force dist\SesDefteri-Basit-Setup.exe $dest
} else { Write-Warning "Inno Setup 6 not found: no Setup.exe (the folder and .zip are still built)" }
Write-Host "Done: $dest"
