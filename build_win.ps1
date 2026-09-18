# Builds dist\나만의빛\나만의빛.exe on Windows. Run from PowerShell:
#   powershell -ExecutionPolicy Bypass -File build_win.ps1
# Keep this file UTF-8 *with BOM*: Windows PowerShell 5.1 otherwise decodes
# it as ANSI and the Korean strings break the parser.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$AppName = "나만의빛"
$Version = (Get-Content VERSION -Raw).Trim()
# Distribution files keep ASCII names so their download URLs stay readable.
$Zip = "dist\Namanuibit-windows-x64.zip"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    uv venv --python 3.12
}
uv pip install -r requirements.lock.txt -r requirements.build.txt

.venv\Scripts\python.exe assets\make_icons.py
Remove-Item -Recurse -Force build, "dist\$AppName" -ErrorAction SilentlyContinue
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean lightloom.spec

if (-not (Test-Path "dist\$AppName\$AppName.exe")) {
    throw "PyInstaller did not produce dist\$AppName\$AppName.exe"
}

# The archive is written entry by entry because the two built-in options both
# get it wrong on Windows PowerShell: Compress-Archive writes entry names in the
# system codepage, mangling the Korean names, and .NET Framework's
# ZipFile.CreateFromDirectory separates them with backslashes, which the ZIP
# spec does not allow. Entries below are UTF-8 and slash separated.
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$root = (Resolve-Path "dist\$AppName").Path
$stream = [System.IO.File]::Open(
    (Join-Path (Resolve-Path "dist").Path (Split-Path $Zip -Leaf)),
    [System.IO.FileMode]::Create)
$archive = New-Object System.IO.Compression.ZipArchive(
    $stream, [System.IO.Compression.ZipArchiveMode]::Create, $false, [System.Text.Encoding]::UTF8)
try {
    foreach ($file in Get-ChildItem -LiteralPath $root -Recurse -File) {
        $relative = $file.FullName.Substring($root.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, $file.FullName, "$AppName/$relative",
            [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $archive.Dispose()
    $stream.Dispose()
}

# Optional single-file installer, when Inno Setup is available.
$iscc = $null
$command = Get-Command iscc -ErrorAction SilentlyContinue
if ($command) {
    $iscc = $command.Source
} else {
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        $candidate = Join-Path $base "Inno Setup 6\ISCC.exe"
        if ($base -and (Test-Path $candidate)) { $iscc = $candidate; break }
    }
}
if ($iscc) {
    & $iscc "/DMyAppVersion=$Version" "packaging\lightloom.iss"
} else {
    Write-Host "Inno Setup(ISCC.exe)가 없어 설치 프로그램은 건너뜁니다. https://jrsoftware.org/isdl.php"
}

Write-Host ""
Write-Host "완료: dist\$AppName\$AppName.exe"
Write-Host "      $Zip"
