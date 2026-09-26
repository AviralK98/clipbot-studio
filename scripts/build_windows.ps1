# Builds the Windows app: dist\ClipBot\ClipBot.exe, and dist\ClipBot-Setup.exe when Inno Setup is installed.
# Run from anywhere:  powershell -File scripts\build_windows.ps1
param([switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = '.\.venv\Scripts\python.exe'

Write-Host '1/4 Building the dashboard as plain files (apps\frontend\out)'
Push-Location apps\frontend
$env:CLIPBOT_STATIC = '1'
try { npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed' } }
finally { Remove-Item Env:CLIPBOT_STATIC -ErrorAction SilentlyContinue; Pop-Location }

Write-Host '2/4 Making the icon'
New-Item -ItemType Directory -Force build | Out-Null
& $python -c "from clipbot.desktop import brand_image; brand_image(256).save('build/clipbot.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw 'Icon build failed' }

Write-Host '3/4 Packaging ClipBot.exe'
& $python -m PyInstaller packaging\clipbot.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }

Write-Host '4/4 Installer'
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($SkipInstaller -or -not $iscc) {
    Write-Host 'Skipped (Inno Setup 6 not found). dist\ClipBot\ClipBot.exe runs as it is.'
} else {
    & $iscc packaging\clipbot.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
    Write-Host 'Done: dist\ClipBot-Setup.exe'
}
