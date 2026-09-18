# Builds dist\나만의빛\나만의빛.exe on Windows. Run from PowerShell:
#   powershell -ExecutionPolicy Bypass -File build_win.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$AppName = "나만의빛"
$Version = (Get-Content VERSION -Raw).Trim()

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    uv venv --python 3.12
}
uv pip install -r requirements.lock.txt -r requirements.build.txt

.venv\Scripts\python.exe assets\make_icons.py
Remove-Item -Recurse -Force build, "dist\$AppName" -ErrorAction SilentlyContinue
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean lightloom.spec

# A single distributable file. Users with WebView2 already installed (Win 11 and
# up-to-date Win 10) can run it straight from the zip.
$zip = "dist\$AppName-$Version-windows.zip"
Remove-Item -Force $zip -ErrorAction SilentlyContinue
Compress-Archive -Path "dist\$AppName\*" -DestinationPath $zip

# Optional single-file installer, if Inno Setup is on PATH.
if (Get-Command iscc -ErrorAction SilentlyContinue) {
    iscc /DMyAppVersion=$Version packaging\lightloom.iss
} else {
    Write-Host "Inno Setup(iscc)가 없어 설치 프로그램은 건너뜁니다. https://jrsoftware.org/isdl.php"
}

Write-Host ""
Write-Host "완료: dist\$AppName\$AppName.exe"
Write-Host "      $zip"
