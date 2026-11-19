# Build the Windows app.
#   .\build_windows.ps1        -> dist\SesDefteri.zip          (any PC: CPU, plus AMD/Intel/NVIDIA GPUs via Vulkan)
#   .\build_windows.ps1 -Gpu   -> also dist\SesDefteri-NVIDIA.zip (adds CUDA libraries: fastest on NVIDIA, ~1.4 GB)
# Vulkan needs vendor\whispercpp (run tools\build_whispercpp.ps1 once); without it the build is CPU/CUDA only.
param([switch]$Gpu)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
.\.venv\Scripts\pip install -q -r requirements.txt pyinstaller
.\.venv\Scripts\python fetch_models.py
if (-not (Test-Path vendor\whispercpp\whisper-cli.exe)) { Write-Warning "vendor\whispercpp missing: this build has no Vulkan (AMD/Intel) support" }
.\.venv\Scripts\pyinstaller --noconfirm --clean SesDefteri.spec
Push-Location dist; & "$env:SystemRoot\System32\tar.exe" -a -c -f SesDefteri.zip SesDefteri; Pop-Location

if ($Gpu) {
    .\.venv\Scripts\pip install -q -r requirements-gpu.txt
    $dst = "dist\SesDefteri-NVIDIA"
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item -Recurse dist\SesDefteri $dst
    # the app looks for <app>\_internal\nvidia\*\bin\*.dll at start-up
    foreach ($pkg in "cublas", "cudnn", "cuda_nvrtc") {
        $src = ".venv\Lib\site-packages\nvidia\$pkg\bin"
        if (Test-Path $src) {
            $to = "$dst\_internal\nvidia\$pkg\bin"
            New-Item -ItemType Directory -Force $to | Out-Null
            Copy-Item "$src\*.dll" $to
        }
    }
    Push-Location dist; & "$env:SystemRoot\System32\tar.exe" -a -c -f SesDefteri-NVIDIA.zip SesDefteri-NVIDIA; Pop-Location  # Windows' own tar writes real zip files (Git's tar.exe would not)
}
# installers (Inno Setup 6): per-user install with Start menu and desktop shortcuts
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q /DSrc=..\dist\SesDefteri /DOutName=SesDefteri-Setup installer\SesDefteri.iss
    if ($Gpu) { & $iscc /Q /DSrc=..\dist\SesDefteri-NVIDIA /DOutName=SesDefteri-NVIDIA-Setup installer\SesDefteri.iss }
} else { Write-Warning "Inno Setup 6 not found: no Setup.exe (the .zip files are still built)" }
Write-Host "Done. Share dist\SesDefteri-Setup.exe (or the .zip files: unzip, run SesDefteri.exe)"
