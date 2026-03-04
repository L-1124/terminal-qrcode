Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 使用 vcpkg 安装静态链接库（头文件 + .lib 静态库）
# 静态链接后 wheel 无需捆绑 DLL

function Invoke-WithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [string]$Name = "command",
        [int]$MaxAttempts = 5,
        [int]$BaseDelaySeconds = 2
    )

    $attempt = 1
    while ($attempt -le $MaxAttempts) {
        try {
            & $Action
            return
        } catch {
            if ($attempt -ge $MaxAttempts) {
                throw "Failed after $MaxAttempts attempts: $Name. Last error: $($_.Exception.Message)"
            }
            $delay = $BaseDelaySeconds * $attempt
            Write-Host "Attempt $attempt failed for $Name. Retrying in $delay seconds..."
            Start-Sleep -Seconds $delay
            $attempt += 1
        }
    }
}

$vcpkgRoot = Join-Path $env:RUNNER_TEMP "vcpkg"
if (-not (Test-Path $vcpkgRoot)) {
    Invoke-WithRetry -Name "git clone vcpkg" -Action { git clone --depth 1 https://github.com/microsoft/vcpkg.git $vcpkgRoot }
}

$bootstrap = Join-Path $vcpkgRoot "bootstrap-vcpkg.bat"
Invoke-WithRetry -Name "bootstrap vcpkg" -Action {
    & cmd /c $bootstrap
    if ($LASTEXITCODE -ne 0) {
        throw "bootstrap-vcpkg.bat failed with exit code $LASTEXITCODE"
    }
}

$vcpkg = Join-Path $vcpkgRoot "vcpkg.exe"
if (-not (Test-Path $vcpkg)) {
    throw "vcpkg executable not found after bootstrap: $vcpkg"
}

Invoke-WithRetry -Name "vcpkg install dependencies" -Action {
    & $vcpkg install libjpeg-turbo:x64-windows-static libpng:x64-windows-static "libwebp[core]:x64-windows-static"
    if ($LASTEXITCODE -ne 0) {
        throw "vcpkg install failed with exit code $LASTEXITCODE"
    }
}

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
