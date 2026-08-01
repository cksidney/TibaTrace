<#
.SYNOPSIS
    Enrols the TibaTrace signing certificate and installs the POS terminal.

.DESCRIPTION
    TibaTrace POS is distributed to managed pharmacy terminals. The installer is
    signed with Esenai Group's own certificate, which is not issued by a public
    certificate authority -- so Windows will not trust it until the public
    certificate is enrolled on the device. That enrolment is what this script
    does, and it is the whole reason the package exists.

    The certificate is pinned. A signed installer is only as trustworthy as the
    key that signed it, so this script refuses to proceed unless the certificate
    in the package, the certificate it imports, and the certificate that signed
    the installer are all the same one. Without that, "signed" only means
    somebody signed it.

    Only the public certificate is ever imported. The private key never leaves
    the signing environment and is not present in this package.

.NOTES
    Run from an elevated PowerShell session on the target terminal.
#>

[CmdletBinding()]
param(
    [string] $PackageRoot,
    [switch] $SkipInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Resolved here, not as a parameter default. Windows PowerShell 5.1 -- which is
# what the guide tells operators to use, and what every Windows terminal has --
# has not populated $PSScriptRoot yet while parameter defaults are being
# evaluated, so `$PackageRoot = $PSScriptRoot` in the param block silently
# yields an empty string and every path built from it fails.
if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = $PSScriptRoot }
if ([string]::IsNullOrWhiteSpace($PackageRoot) -and $MyInvocation.MyCommand.Path) {
    $PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    throw 'Could not determine the package directory. Pass it explicitly: -PackageRoot <path to the extracted folder>.'
}

# Injected at package time from the certificate that actually signed this
# installer. A literal here rather than a value read from the package: reading
# the expected thumbprint out of the same folder it is checking would verify
# nothing at all.
$ExpectedCertificateSha256 = '__PINNED_CERT_SHA256__'
$ExpectedSignerSha256      = '__PINNED_CERT_SHA256__'

$InstallerName   = 'TibaTrace-POS-Setup-__INSTALLER_VERSION__.exe'
$CertificateName = 'tibatrace-windows-signing.cer'
$ExpectedSubject = 'CN=Esenai Group Ltd, O=Esenai Group Ltd, C=KE'

function Write-Step { param([string] $Message) Write-Host "`n=== $Message" -ForegroundColor Cyan }
function Write-Good { param([string] $Message) Write-Host "    $Message" -ForegroundColor Green }
function Write-Info { param([string] $Message) Write-Host "    $Message" }

function Get-CertificateSha256 {
    <#
        The SHA-256 of the certificate's DER bytes.

        Not $cert.Thumbprint, which is SHA-1. SHA-1 is collision-prone and has no
        business being the thing a trust decision is pinned to.
    #>
    param([Security.Cryptography.X509Certificates.X509Certificate2] $Certificate)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        ($sha256.ComputeHash($Certificate.RawData) | ForEach-Object { $_.ToString('x2') }) -join ''
    }
    finally {
        $sha256.Dispose()
    }
}

# --- 1. Administrator --------------------------------------------------------

Write-Step 'Checking privileges'
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'This script must be run from an elevated PowerShell session. Writing to the machine certificate store and installing per-machine both require it.'
}
Write-Good "Running elevated as $($identity.Name)."

# --- 2. Package contents -----------------------------------------------------

Write-Step 'Locating package contents'
$certPath      = Join-Path $PackageRoot $CertificateName
$installerPath = Join-Path $PackageRoot $InstallerName

foreach ($required in @($certPath, $installerPath)) {
    if (-not (Test-Path $required)) {
        throw "Missing from the package: $required. Extract the whole ZIP and run this script from inside it."
    }
}
Write-Good "Found $CertificateName and $InstallerName."

# --- 3. The certificate, before anything is trusted --------------------------

Write-Step 'Inspecting the certificate'
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($certPath)
$certSha256  = Get-CertificateSha256 -Certificate $certificate

Write-Info "Subject      : $($certificate.Subject)"
Write-Info "Issuer       : $($certificate.Issuer)"
Write-Info "Valid from   : $($certificate.NotBefore.ToString('u'))"
Write-Info "Valid to     : $($certificate.NotAfter.ToString('u'))"
Write-Info "SHA-256      : $certSha256"
Write-Info "SHA-1        : $($certificate.Thumbprint)"

if ($certificate.HasPrivateKey) {
    # A .cer carries a public certificate. A private key in this package would
    # mean the signing key had been distributed to every terminal.
    throw 'The certificate in this package contains a private key. Stop and report this: the package is not safe to deploy.'
}
Write-Good 'Public certificate only, no private key.'

if ($certSha256 -ne $ExpectedCertificateSha256) {
    throw @"
Certificate does not match the pinned thumbprint.
  expected : $ExpectedCertificateSha256
  found    : $certSha256
The package has been altered or is not the one it claims to be. Do not continue.
"@
}
Write-Good 'Certificate matches the pinned SHA-256.'

if ($certificate.Subject -ne $ExpectedSubject) {
    throw "Certificate subject is '$($certificate.Subject)', expected '$ExpectedSubject'."
}
Write-Good 'Subject matches.'

$now = Get-Date
if ($now -lt $certificate.NotBefore -or $now -gt $certificate.NotAfter) {
    throw "Certificate is outside its validity window ($($certificate.NotBefore.ToString('u')) to $($certificate.NotAfter.ToString('u')))."
}
Write-Good 'Certificate is within its validity window.'

# --- 4. Signature before enrolment -------------------------------------------

Write-Step 'Checking the installer signature before enrolment'
$before = Get-AuthenticodeSignature -FilePath $installerPath
Write-Info "Status: $($before.Status)"
if ($before.Status -eq 'Valid') {
    Write-Good 'Already trusted on this device; the certificate is presumably enrolled.'
} else {
    # Expected on a device that has not been enrolled. Reported rather than
    # treated as an error, because it is the condition this script exists for.
    Write-Info 'Not yet trusted, which is expected before enrolment.'
}

if ($null -eq $before.SignerCertificate) {
    throw 'The installer carries no Authenticode signature at all. Do not continue.'
}

$signerSha256 = Get-CertificateSha256 -Certificate $before.SignerCertificate
Write-Info "Signer       : $($before.SignerCertificate.Subject)"
Write-Info "Signer SHA256: $signerSha256"

if ($signerSha256 -ne $ExpectedSignerSha256) {
    throw @"
The installer was signed by a different certificate than the one in this package.
  expected : $ExpectedSignerSha256
  signer   : $signerSha256
Enrolling this certificate would not make that installer trustworthy. Stop.
"@
}
Write-Good 'Installer signer matches the pinned certificate.'

# --- 5. Enrolment ------------------------------------------------------------

Write-Step 'Enrolling the public certificate'

# TrustedPeople holds publishers this machine accepts directly. For a
# self-signed certificate the chain also terminates here, so Root is required
# as well for Authenticode to report Valid -- TrustedPeople alone establishes
# the publisher but leaves the chain untrusted.
$stores = @('TrustedPeople', 'Root')
foreach ($storeName in $stores) {
    $store = [Security.Cryptography.X509Certificates.X509Store]::new(
        $storeName, [Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine)
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    try {
        $existing = $store.Certificates | Where-Object { (Get-CertificateSha256 -Certificate $_) -eq $certSha256 }
        if ($existing) {
            Write-Info "Already present in LocalMachine\$storeName."
        } else {
            $store.Add($certificate)
            Write-Good "Imported into LocalMachine\$storeName."
        }
    }
    finally {
        $store.Close()
    }
}

# --- 6. Verify the enrolment landed ------------------------------------------

Write-Step 'Verifying enrolment'
foreach ($storeName in $stores) {
    $found = Get-ChildItem "Cert:\LocalMachine\$storeName" |
        Where-Object { (Get-CertificateSha256 -Certificate $_) -eq $certSha256 }
    if (-not $found) {
        throw "Certificate is not present in LocalMachine\$storeName after import."
    }
    Write-Good "Confirmed in LocalMachine\$storeName."
}

# --- 7. Signature after enrolment --------------------------------------------

Write-Step 'Re-checking the installer signature'
$after = Get-AuthenticodeSignature -FilePath $installerPath
Write-Info "Status: $($after.Status)"

$afterSignerSha256 = Get-CertificateSha256 -Certificate $after.SignerCertificate
if ($afterSignerSha256 -ne $ExpectedSignerSha256) {
    throw 'The installer signer changed between checks. Stop and investigate.'
}

if ($after.Status -ne 'Valid') {
    throw @"
The installer signature is still '$($after.Status)' after enrolment.
Expected 'Valid'. Do not run the installer: something about the signature or the
certificate chain is not what this package expects.
"@
}
Write-Good 'Authenticode reports Valid.'

if ($null -eq $after.TimeStamperCertificate) {
    Write-Warning 'The signature is not timestamped; it will stop validating when the certificate expires.'
} else {
    Write-Good "Timestamped by $($after.TimeStamperCertificate.Subject)."
}

# --- 8. Install --------------------------------------------------------------

if ($SkipInstall) {
    Write-Step 'Verification complete; skipping installation as requested'
    exit 0
}

Write-Step 'Installing TibaTrace POS'
Write-Info "Running $InstallerName ..."
# /S is the NSIS silent switch. Reaching here means the installer's signature
# has been verified against a pinned certificate, so running it unattended is a
# decision this script has already justified.
$process = Start-Process -FilePath $installerPath -ArgumentList '/S' -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "The installer exited with code $($process.ExitCode)."
}
Write-Good 'Installer completed.'

Write-Step 'Done'
Write-Info 'TibaTrace POS is installed and the signing certificate is enrolled on this device.'
