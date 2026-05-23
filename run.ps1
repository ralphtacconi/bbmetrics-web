param(
  [string]$BaseUrl    = "https://git.rdisoftware.com:8443",
  [string]$ProjectKey = "KIOSK",
  [string]$OutDir     = ".\out",
  [string]$User       = "rtacco",  # opcional: filtra PR author (username do Bitbucket DC)
  [string[]]$Repos,            # opcional: filtra repos (aceita 1 ou mais). Ex: "Kiosk","KioskAutomation"
  [string]$PrStart,            # opcional: filtro data início PR (MM-DD-YYYY)
  [string]$PrEnd,              # opcional: filtro data fim PR (MM-DD-YYYY)
  [string]$DebugDiffstatDir    # opcional: salva JSON/erros do diffstat para diagnosticar lines_* = 0
)

Set-Location -Path $PSScriptRoot

$ErrorActionPreference = "Stop"

Write-Host "== Bitbucket DC Metrics =="
Write-Host "BaseUrl:    $BaseUrl"
Write-Host "ProjectKey: $ProjectKey"
Write-Host "OutDir:     $OutDir"
if ($User)            { Write-Host "User:       $User" }
if ($Repos)           { Write-Host "Repos:      $($Repos -join ', ')" }
if ($PrStart)         { Write-Host "PrStart:    $PrStart" }
if ($PrEnd)           { Write-Host "PrEnd:      $PrEnd" }
if ($DebugDiffstatDir){ Write-Host "DebugDiffstatDir: $DebugDiffstatDir" }

# 1) Venv
if (!(Test-Path ".\.venv")) {
  Write-Host "Creating venv..."
  py -m venv .venv
}

Write-Host "Activating venv..."
& ".\.venv\Scripts\Activate.ps1"

# 2) Dependencies
Write-Host "Installing dependencies..."
pip install -r requirements.txt | Out-Host

# 3) Credentials (prompt se não estiverem setadas)
if (-not $env:BITBUCKET_USERNAME) {
  $env:BITBUCKET_USERNAME = Read-Host "BITBUCKET_USERNAME"
}
if (-not $env:BITBUCKET_PASSWORD) {
  $secure = Read-Host "BITBUCKET_PASSWORD (use TOKEN)" -AsSecureString
  $env:BITBUCKET_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  )
}

# 4) Base URL
$env:BITBUCKET_BASE_URL = $BaseUrl

# 5) Run
Write-Host "Running collector..."

# Monte como ARRAY (cada argumento separado)
$cmd = @(
  "python", "-m", "bbmetrics_dc.cli",
  "--project-key", $ProjectKey,
  "--out", $OutDir
)

if ($User) {
  $cmd += @("--user", $User)
}

if ($Repos) {
  foreach ($r in $Repos) {
    $cmd += @("--repos", $r)
  }
}

# NEW: date filters
if ($PrStart) {
  $cmd += @("--pr-start", $PrStart)
}
if ($PrEnd) {
  $cmd += @("--pr-end", $PrEnd)
}

# NEW: diffstat debug dump dir (requires cli.py with --debug-diffstat-dir option)
if ($DebugDiffstatDir) {
  $cmd += @("--debug-diffstat-dir", $DebugDiffstatDir)
}

Write-Host ("DEBUG CMD: " + ($cmd -join " "))

& $cmd[0] $cmd[1..($cmd.Length-1)]

Write-Host "Done. CSVs in: $OutDir"