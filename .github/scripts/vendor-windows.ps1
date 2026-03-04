Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 使用 vcpkg 安装静态链接库（头文件 + .lib 静态库）
# 静态链接后 wheel 无需捆绑 DLL

$vcpkgRoot = Join-Path $env:RUNNER_TEMP "vcpkg"
if (-not (Test-Path $vcpkgRoot)) {
    git clone https://github.com/microsoft/vcpkg.git $vcpkgRoot
}

$bootstrap = Join-Path $vcpkgRoot "bootstrap-vcpkg.bat"
& cmd /c $bootstrap

$vcpkg = Join-Path $vcpkgRoot "vcpkg.exe"
& $vcpkg install libjpeg-turbo:x64-windows-static libpng:x64-windows-static "libwebp[core]:x64-windows-static"

$installedDir = Join-Path $vcpkgRoot "installed\x64-windows-static"
$includeDir = Join-Path $installedDir "include"
$libDir = Join-Path $installedDir "lib"

if (-not (Test-Path $includeDir)) {
    throw "vcpkg include directory not found: $includeDir"
}
if (-not (Test-Path $libDir)) {
    throw "vcpkg lib directory not found: $libDir"
}

Write-Host "vcpkg static libraries installed."
Write-Host "Include: $includeDir"
Write-Host "Lib: $libDir"
Get-ChildItem -Path $libDir -Filter "*.lib" | ForEach-Object { Write-Host "  $($_.Name) ($($_.Length) bytes)" }
