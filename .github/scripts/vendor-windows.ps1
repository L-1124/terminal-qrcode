Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$OutDir = Join-Path $RootDir "src\terminal_qrcode\_vendor\windows"

if (Test-Path $OutDir) {
    Remove-Item -Recurse -Force $OutDir
}
New-Item -ItemType Directory -Path $OutDir | Out-Null

$vcpkgRoot = Join-Path $env:RUNNER_TEMP "vcpkg"
if (-not (Test-Path $vcpkgRoot)) {
    git clone https://github.com/microsoft/vcpkg.git $vcpkgRoot
}

$bootstrap = Join-Path $vcpkgRoot "bootstrap-vcpkg.bat"
& cmd /c $bootstrap

$vcpkg = Join-Path $vcpkgRoot "vcpkg.exe"
& $vcpkg install libjpeg-turbo:x64-windows libpng:x64-windows libwebp:x64-windows

$binDir = Join-Path $vcpkgRoot "installed\x64-windows\bin"

function Copy-LibIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$TargetName
    )
    if (Test-Path $SourcePath) {
        Copy-Item -Path $SourcePath -Destination (Join-Path $OutDir $TargetName) -Force
        return $true
    }
    return $false
}

if (-not (Copy-LibIfExists -SourcePath (Join-Path $binDir "turbojpeg.dll") -TargetName "turbojpeg.dll")) {
    throw "turbojpeg.dll not found in $binDir"
}

$libpngCandidates = Get-ChildItem -Path $binDir -Filter "libpng*.dll" | Sort-Object Name
if (-not $libpngCandidates) {
    throw "libpng DLL not found in $binDir"
}
$libpngPrimary = $libpngCandidates[0].FullName
Copy-Item -Path $libpngPrimary -Destination (Join-Path $OutDir (Split-Path $libpngPrimary -Leaf)) -Force

$libpng1616 = Join-Path $OutDir "libpng16-16.dll"
$libpng16 = Join-Path $OutDir "libpng16.dll"
if (-not (Test-Path $libpng1616)) {
    Copy-Item -Path $libpngPrimary -Destination $libpng1616 -Force
}
if (-not (Test-Path $libpng16)) {
    Copy-Item -Path $libpngPrimary -Destination $libpng16 -Force
}

if (-not (Copy-LibIfExists -SourcePath (Join-Path $binDir "libwebp.dll") -TargetName "libwebp.dll")) {
    throw "libwebp.dll not found in $binDir"
}

$libsixel = Join-Path $binDir "libsixel.dll"
if (Test-Path $libsixel) {
    Copy-Item -Path $libsixel -Destination (Join-Path $OutDir "libsixel.dll") -Force
}
else {
    Write-Warning "libsixel.dll not found on Windows runner; keep fallback behavior."
}

Write-Host "Bundled Windows libraries:"
Get-ChildItem -Path $OutDir | Format-Table Name, Length
