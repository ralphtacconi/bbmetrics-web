$ErrorActionPreference = "Stop"

Set-Location -Path (Join-Path $PSScriptRoot "..")

function Remove-DirWithRetry([string]$Path, [int]$Retries = 6) {
  if (!(Test-Path $Path)) { return }

  for ($i = 0; $i -lt $Retries; $i++) {
    try { attrib -R "$Path\*" /S /D 2>$null | Out-Null } catch {}

    try {
      Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
      return
    } catch {
      Start-Sleep -Milliseconds (400 * ($i + 1))
    }
  }

  throw "Failed to remove directory after retries: $Path"
}

Write-Host "Killing running BBMetrics_UI.exe (if any)..."
Get-Process -Name "BBMetrics_UI" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 400

if (!(Test-Path ".\.venv")) {
  py -m venv .venv
}
& ".\.venv\Scripts\Activate.ps1"

pip install -r requirements.txt | Out-Host
pip install pyinstaller | Out-Host

$buildDir = Join-Path $PSScriptRoot "..\build\BBMetrics_UI"
$distDir  = Join-Path $PSScriptRoot "..\dist\BBMetrics_UI"

Write-Host "Cleaning build/dist..."
Remove-DirWithRetry $buildDir
Remove-DirWithRetry $distDir

Write-Host "Running PyInstaller (spec)..."
pyinstaller `
  --noconfirm `
  --clean `
  "BBMetrics_UI.spec"

if (!(Test-Path $distDir)) {
  throw "PyInstaller did not produce expected output dir: $distDir"
}

# Ensure ZIP contains editable users.csv BEFORE first run
$srcUsers = Join-Path $PSScriptRoot "..\in\users.csv"
if (!(Test-Path $srcUsers)) {
  throw "Missing source users.csv at: $srcUsers"
}

$dstInDir = Join-Path $distDir "in"
$dstUsers = Join-Path $dstInDir "users.csv"
New-Item -ItemType Directory -Force -Path $dstInDir | Out-Null
Copy-Item -LiteralPath $srcUsers -Destination $dstUsers -Force
Write-Host "Copied users.csv to: $dstUsers"

# zip a pasta inteira
$zipOut = Join-Path $PSScriptRoot "..\dist\BBMetrics_UI.zip"
if (Test-Path $zipOut) { Remove-Item $zipOut -Force }

Write-Host "Creating ZIP..."
Compress-Archive -Path $distDir -DestinationPath $zipOut

Write-Host "DIR: $distDir"
Write-Host "ZIP: $zipOut"