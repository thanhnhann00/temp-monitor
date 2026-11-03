# Downloads third-party files Thermo needs at runtime. Run from the temp-monitor folder:
#   powershell -ExecutionPolicy Bypass -File tools\fetch_vendor.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$LhmVersion = "0.9.4"
$HidSharpVersion = "2.1.0"
$ChartVersion = "4.4.7"
$FontVersion = "5.1.0"

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("thermo-vendor-" + [Guid]::NewGuid())
New-Item -ItemType Directory -Force $tmp | Out-Null
New-Item -ItemType Directory -Force (Join-Path $root "lib") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $root "static\vendor\fonts") | Out-Null

function Get-NuGetDll($id, $version, $dllName) {
    $pkg = Join-Path $tmp "$id.$version.zip"
    Invoke-WebRequest "https://www.nuget.org/api/v2/package/$id/$version" -OutFile $pkg
    $dir = Join-Path $tmp "$id.$version"
    Expand-Archive $pkg $dir
    $dll = Get-ChildItem -Recurse $dir -Filter $dllName |
        Where-Object { $_.FullName -match '\\lib\\net[34]' } |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $dll) { throw "$dllName (.NET Framework build) not found in $id $version" }
    Copy-Item $dll.FullName (Join-Path $root "lib") -Force
    Write-Host "lib\$dllName  <- $id $version ($($dll.Directory.Name))"
}

Get-NuGetDll "LibreHardwareMonitorLib" $LhmVersion "LibreHardwareMonitorLib.dll"
Get-NuGetDll "HidSharp" $HidSharpVersion "HidSharp.dll"

Invoke-WebRequest "https://cdn.jsdelivr.net/npm/chart.js@$ChartVersion/dist/chart.umd.js" `
    -OutFile (Join-Path $root "static\vendor\chart.umd.min.js")
Write-Host "static\vendor\chart.umd.min.js  <- chart.js $ChartVersion"

foreach ($w in 400, 500, 600, 700) {
    $name = "plus-jakarta-sans-latin-$w-normal.woff2"
    Invoke-WebRequest "https://cdn.jsdelivr.net/npm/@fontsource/plus-jakarta-sans@$FontVersion/files/$name" `
        -OutFile (Join-Path $root "static\vendor\fonts\$name")
    Write-Host "static\vendor\fonts\$name"
}

Remove-Item -Recurse -Force $tmp
