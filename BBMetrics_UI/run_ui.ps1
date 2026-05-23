$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot\..

if (!(Test-Path ".\.venv")) {
  py -m venv .venv
}

& ".\.venv\Scripts\Activate.ps1"
pip install -r requirements.txt | Out-Host

python -m BBMetrics_UI.app