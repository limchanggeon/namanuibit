# Starts the packaged app headlessly enough to prove the bundle imports rawpy,
# scipy and Pillow, serves the UI, and renders an export end to end.
$ErrorActionPreference = "Stop"
$exe = "dist\나만의빛\나만의빛.exe"
if (-not (Test-Path $exe)) { throw "missing $exe" }

# Entry names must be UTF-8 and slash separated or the Korean folder unpacks
# as mojibake, or as one file with a backslash in its name.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path "dist\Namanuibit-windows-x64.zip").Path)
try {
    $names = $archive.Entries | ForEach-Object { $_.FullName }
    $backslashed = $names | Where-Object { $_ -match '\\' }
    if ($backslashed) { throw "zip entries use backslashes: $($backslashed[0])" }
    if (-not ($names -contains "나만의빛/나만의빛.exe")) {
        throw "나만의빛/나만의빛.exe missing from the archive; first entry is $($names[0])"
    }
    Write-Host "archive: $($names.Count) entries, names intact"
} finally {
    $archive.Dispose()
}

$env:LIGHTLOOM_PORT = "8791"
$env:LIGHTLOOM_DATA = Join-Path $env:RUNNER_TEMP "library"
$app = Start-Process -FilePath $exe -PassThru

try {
    $health = $null
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 2
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:8791/api/health" -TimeoutSec 5
            break
        } catch { }
    }
    if (-not $health) { throw "the packaged app never answered on 127.0.0.1:8791" }
    Write-Host "health: $($health | ConvertTo-Json -Compress)"

    # A small photo through import -> render -> export exercises rawpy's import,
    # the scipy filters and the Pillow encoder inside the frozen bundle.
    Add-Type -AssemblyName System.Drawing
    $bitmap = New-Object System.Drawing.Bitmap 400, 300
    for ($x = 0; $x -lt 400; $x++) {
        for ($y = 0; $y -lt 300; $y++) {
            $bitmap.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(($x % 256), ($y % 256), 128))
        }
    }
    $photo = Join-Path $env:RUNNER_TEMP "sample.png"
    $bitmap.Save($photo, [System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()

    $form = @{ file = Get-Item $photo }
    $imported = Invoke-RestMethod "http://127.0.0.1:8791/api/photos" -Method Post -Form $form
    Write-Host "imported: $($imported.id) $($imported.width)x$($imported.height)"

    $body = @{
        settings = @{ exposure = 0.5; clarity = 20; vignette = -15 }
        format   = "jpeg"
        quality  = 92
    } | ConvertTo-Json
    $out = Join-Path $env:RUNNER_TEMP "exported.jpg"
    Invoke-WebRequest "http://127.0.0.1:8791/api/photos/$($imported.id)/export" `
        -Method Post -ContentType "application/json" -Body $body -OutFile $out
    $size = (Get-Item $out).Length
    if ($size -lt 1000) { throw "export produced only $size bytes" }
    Write-Host "exported $size bytes - bundle works"
} finally {
    if ($app -and -not $app.HasExited) { Stop-Process -Id $app.Id -Force }
}
