# ==============================================================================
# Homelab OS (HL-OS) — Windows PowerShell Dependency-First Bootstrapper
# Checks & installs ALL host/service dependencies FIRST (Python 3.12, Git/OpenSSL,
# Docker Desktop, Tailscale), then installs `homelab-os` and runs `homelab init`.
#
# Usage:
#   irm https://raw.githubusercontent.com/beingbrijesh/homelab-framework/main/scripts/install.ps1 | iex
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Yes -Start
# ==============================================================================

param(
    [switch]$Yes,
    [switch]$Start,
    [string]$Dir = "",
    [string]$Storage = "",
    [string]$Domain = "",
    [string]$PackageSpec = "homelab-os"
)

$ErrorActionPreference = "Stop"

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Find-Python {
    foreach ($candidate in @("py", "python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                if ($candidate -eq "py") {
                    & py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
                    if ($LASTEXITCODE -eq 0) { return @("py", "-3") }
                } else {
                    & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
                    if ($LASTEXITCODE -eq 0) { return @($candidate) }
                }
            } catch {}
        }
    }
    return $null
}

function Confirm-Action($Message) {
    if ($Yes) { return $true }
    $resp = Read-Host "$Message [Y/n]"
    return ($resp -eq "" -or $resp -match "^[Yy]")
}

function Install-WingetPkg($Id, $Label) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget not found. Install $Label manually and re-run."
    }
    winget install --id $Id -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
}

Write-Host "=== Step 1/3: Checking & Installing All Host & Service Dependencies First ===" -ForegroundColor Cyan

$pyCmd = Find-Python
if (-not $pyCmd) {
    Write-Warning "Python 3.9+ is missing."
    if (-not (Confirm-Action "Install Python 3.12 automatically via winget?")) {
        throw "Python 3.9+ is required before installing Homelab OS."
    }
    Install-WingetPkg "Python.Python.3.12" "Python 3.12"
    $pyCmd = Find-Python
    if (-not $pyCmd) {
        throw "Python installation completed; please open a new PowerShell window and re-run."
    }
}
Write-Host "[OK] Python verified." -ForegroundColor Green

$gitOk = [bool](Get-Command git -ErrorAction SilentlyContinue)
$sslPath = Join-Path $env:ProgramFiles "Git\usr\bin\openssl.exe"
$sslOk = [bool](Get-Command openssl -ErrorAction SilentlyContinue) -or (Test-Path $sslPath)
if (-not ($gitOk -and $sslOk)) {
    Write-Warning "Git / OpenSSL tools are missing."
    if (-not (Confirm-Action "Install Git (includes OpenSSL) via winget?")) {
        throw "Git and OpenSSL are required before Homelab OS setup."
    }
    Install-WingetPkg "Git.Git" "Git for Windows"
}
Write-Host "[OK] Git & OpenSSL verified." -ForegroundColor Green

$tsExe = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
$tsOk = [bool](Get-Command tailscale -ErrorAction SilentlyContinue) -or (Test-Path $tsExe)
if (-not $tsOk) {
    Write-Warning "Tailscale mesh VPN client is missing."
    if (-not (Confirm-Action "Install Tailscale automatically via winget?")) {
        throw "Tailscale is required before Homelab OS setup."
    }
    Install-WingetPkg "Tailscale.Tailscale" "Tailscale"
}
Write-Host "[OK] Tailscale verified." -ForegroundColor Green

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Warning "Docker Desktop / Docker CLI is missing."
    if (-not (Confirm-Action "Install Docker Desktop automatically via winget?")) {
        throw "Docker Desktop is required before Homelab OS setup."
    }
    Install-WingetPkg "Docker.DockerDesktop" "Docker Desktop"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI still not detected in PATH. Open a new terminal / start Docker Desktop and re-run."
}

& docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $desktopExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktopExe) {
        Write-Host "[INFO] Starting Docker Desktop..." -ForegroundColor Yellow
        Start-Process $desktopExe | Out-Null
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 2
            & docker info 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
        }
    }
}
& docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker daemon is not running yet. Finish starting Docker Desktop (WSL2) and re-run."
}
Write-Host "[OK] Docker & Compose v2 verified." -ForegroundColor Green

Write-Host "=== Step 2/3: Installing homelab-os CLI Package ===" -ForegroundColor Cyan
$venvDir = Join-Path $env:USERPROFILE ".homelab\.cli-venv"
if ($pyCmd.Count -eq 2) {
    & $pyCmd[0] $pyCmd[1] -m venv $venvDir
} else {
    & $pyCmd[0] -m venv $venvDir
}
$pipExe = Join-Path $venvDir "Scripts\pip.exe"
$homelabExe = Join-Path $venvDir "Scripts\homelab.exe"
& $pipExe install --upgrade pip | Out-Null
& $pipExe install --upgrade $PackageSpec

$scriptsDir = Join-Path $venvDir "Scripts"
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$scriptsDir*") {
    [System.Environment]::SetEnvironmentVariable("Path", "$userPath;$scriptsDir", "User")
    $env:Path = "$env:Path;$scriptsDir"
}
Write-Host "[OK] Installed homelab CLI at $homelabExe" -ForegroundColor Green

Write-Host "=== Step 3/3: Running Homelab OS Setup ===" -ForegroundColor Cyan
$cliArgs = @("init")
if ($Yes) { $cliArgs += "-y" }
if ($Start) { $cliArgs += "--start" }
if ($Dir) { $cliArgs += @("--dir", $Dir) }
if ($Storage) { $cliArgs += @("--storage", $Storage) }
if ($Domain) { $cliArgs += @("--domain", $Domain) }

& $homelabExe @cliArgs
exit $LASTEXITCODE
