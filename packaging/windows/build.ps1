# Build AIScreeningAssistant.exe and wrap it in an MSI installer.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 [-Version 1.0.0]
#
# Requires: Python 3.11+ with the project's requirements installed, and the
# WiX v5 CLI (installed below if missing via `dotnet tool`).
param([string]$Version = "1.0.0")

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Root

Write-Host "==> Generating icons"
python packaging\make_icons.py

Write-Host "==> Freezing the app"
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }
python -m PyInstaller packaging\ai-screening.spec --noconfirm --log-level WARN

$Payload = Join-Path $Root "dist\AIScreeningAssistant"
if (-not (Test-Path $Payload)) { throw "PyInstaller did not produce $Payload" }
if (-not (Test-Path (Join-Path $Payload "AIScreeningAssistant.exe"))) {
    throw "AIScreeningAssistant.exe missing from $Payload"
}

Write-Host "==> Ensuring the WiX toolset is available"
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    dotnet tool install --global wix --version 5.*
    $env:PATH = "$env:PATH;$env:USERPROFILE\.dotnet\tools"
}
# Directory harvesting via <Files Include="..."> is part of the WiX core, so
# no extension needs registering here.

Write-Host "==> Building the MSI"
$Out = Join-Path $Root "dist\AI-Screening-Assistant-$Version.msi"
wix build packaging\windows\Package.wxs `
    -define "PayloadDir=$Payload" `
    -define "ProductVersion=$Version" `
    -arch x64 `
    -out $Out

if (-not (Test-Path $Out)) { throw "MSI was not produced" }
Write-Host ""
Write-Host "Built: $Out"
Write-Host ""
Write-Host "This MSI is unsigned. SmartScreen will warn on first run until the"
Write-Host "installer is signed with an EV or OV code-signing certificate:"
Write-Host "  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx /p PASSWORD `"$Out`""
