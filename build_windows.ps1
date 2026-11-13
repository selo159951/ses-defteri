# Build the simple app: .\build_windows.ps1  ->  Desktop\SesDefteri-Basit (folder) and Desktop\SesDefteri-Basit.zip
# One package for every PC: runs on the processor, the speech model is downloaded on first start (internet once).
# Uses the Python environment of the full project next to it (..\meet_speech_to_text\.venv).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot "..\meet_speech_to_text\.venv\Scripts"
& "$py\pyinstaller.exe" --noconfirm --clean SesDefteri.spec
# the Visual C++ runtime must be inside the package (a PC without the redistributable still has to work)
foreach ($d in "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "python312.dll") {
    if (-not (Test-Path "dist\SesDefteri\_internal\$d")) { throw "$d is missing from the package" }
}
$desk = [Environment]::GetFolderPath("Desktop")
$out = Join-Path $desk "SesDefteri-Basit"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
Copy-Item -Recurse dist\SesDefteri $out
Copy-Item KULLANIM.txt $out  # the one-page guide next to the exe
$zip = Join-Path $desk "SesDefteri-Basit.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Push-Location $desk; & "$env:SystemRoot\System32\tar.exe" -a -c -f SesDefteri-Basit.zip SesDefteri-Basit; Pop-Location
Write-Host "Done: $out (open SesDefteri.exe) and $zip"
