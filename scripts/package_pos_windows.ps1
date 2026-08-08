param(
    [switch]$SkipMsix,
    [switch]$RequireSigning
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $Root "apps/pos-windows"
$ElectronRoot = Join-Path $Root "node_modules/electron/dist"
$ReleaseRoot = Join-Path $AppRoot "release"
$StageRoot = Join-Path $ReleaseRoot "TibaTrace-POS-win-x64"
$BrandRoot = Join-Path $AppRoot "public/brand"
$Version = "0.1.0.1"

if (-not (Test-Path (Join-Path $ElectronRoot "electron.exe"))) {
    throw "Electron runtime is missing. Run npm ci without --ignore-scripts on Windows."
}

if (Test-Path $StageRoot) {
    Remove-Item $StageRoot -Recurse -Force
}
New-Item $StageRoot -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $ElectronRoot "*") $StageRoot -Recurse -Force
Rename-Item (Join-Path $StageRoot "electron.exe") "TibaTrace POS.exe"

$AppPackage = Join-Path $StageRoot "resources/app"
New-Item $AppPackage -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $AppRoot "dist") $AppPackage -Recurse -Force
@{
    name = "tibatrace-pos"
    version = "0.1.0-alpha.1"
    private = $true
    type = "module"
    main = "dist/main/main.js"
} | ConvertTo-Json | Set-Content (Join-Path $AppPackage "package.json") -Encoding UTF8

$Assets = Join-Path $StageRoot "Assets"
New-Item $Assets -ItemType Directory -Force | Out-Null
Copy-Item -Path (Join-Path $BrandRoot "tibatrace-44.png") -Destination (Join-Path $Assets "Square44x44Logo.png")
Copy-Item -Path (Join-Path $BrandRoot "tibatrace-150.png") -Destination (Join-Path $Assets "Square150x150Logo.png")
Copy-Item -Path (Join-Path $BrandRoot "tibatrace-store.png") -Destination (Join-Path $Assets "StoreLogo.png")

if ($SkipMsix) {
    Write-Host "Windows application staged at $StageRoot"
    exit 0
}

$Publisher = if ($env:TIBATRACE_WINDOWS_PUBLISHER) {
    $env:TIBATRACE_WINDOWS_PUBLISHER
} else {
    "CN=Esenai Health Technologies"
}
$Manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap rescap">
  <Identity Name="Esenai.TibaTracePOS" Publisher="$Publisher" Version="$Version" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>TibaTrace POS</DisplayName>
    <PublisherDisplayName>Esenai Health Technologies</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Applications>
    <Application Id="TibaTracePOS" Executable="TibaTrace POS.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="TibaTrace POS"
                          Description="TibaTrace medicine dispensing point of sale"
                          BackgroundColor="white"
                          Square44x44Logo="Assets\Square44x44Logo.png"
                          Square150x150Logo="Assets\Square150x150Logo.png" />
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
    <Capability Name="internetClient" />
  </Capabilities>
</Package>
"@
$Manifest | Set-Content (Join-Path $StageRoot "AppxManifest.xml") -Encoding UTF8

$WindowsKits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits/10/bin"
$MakeAppx = Get-ChildItem $WindowsKits -Filter MakeAppx.exe -Recurse |
    Where-Object { $_.FullName -match "\\x64\\" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $MakeAppx) {
    throw "MakeAppx.exe was not found in the Windows SDK."
}

$Msix = Join-Path $ReleaseRoot "TibaTrace-POS-0.1.0-alpha.1-x64.msix"
if (Test-Path $Msix) {
    Remove-Item $Msix -Force
}
& $MakeAppx.FullName pack /d $StageRoot /p $Msix /o
if ($LASTEXITCODE -ne 0) {
    throw "MakeAppx failed with exit code $LASTEXITCODE."
}

$SigningConfigured =
    $env:TIBATRACE_WINDOWS_PFX -and
    $env:TIBATRACE_WINDOWS_PFX_PASSWORD -and
    $env:TIBATRACE_WINDOWS_PUBLISHER
if ($RequireSigning -and -not $SigningConfigured) {
    throw "Production packaging requires TIBATRACE_WINDOWS_PFX, TIBATRACE_WINDOWS_PFX_PASSWORD and TIBATRACE_WINDOWS_PUBLISHER."
}
if ($SigningConfigured) {
    $SignTool = Get-ChildItem $WindowsKits -Filter SignTool.exe -Recurse |
        Where-Object { $_.FullName -match "\\x64\\" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if (-not $SignTool) {
        throw "SignTool.exe was not found in the Windows SDK."
    }
    & $SignTool.FullName sign /fd SHA256 /f $env:TIBATRACE_WINDOWS_PFX /p $env:TIBATRACE_WINDOWS_PFX_PASSWORD $Msix
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Windows MSIX created at $Msix"
