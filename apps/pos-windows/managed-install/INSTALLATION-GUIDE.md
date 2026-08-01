# TibaTrace POS — managed device installation

For pharmacy terminals enrolled into a TibaTrace deployment. Version 1.0.0, x64.

---

## What this package is, and why it is not a plain installer

TibaTrace POS is signed with Esenai Group Ltd's own code signing certificate.
That certificate is not issued by a public certificate authority, so a Windows
machine that has never met it will not trust the installer — SmartScreen will
warn, and `Get-AuthenticodeSignature` will report the chain as untrusted.

That is expected, and it is not the same thing as the installer being unsigned.
The file carries a real cryptographic signature, made with a key held only by
Esenai Group, and any tampering after signing invalidates it. What it lacks is a
public certificate authority vouching for that key to machines that have never
seen it.

For a controlled fleet, the fleet operator does the vouching. Enrolling the
public certificate during device provisioning is the intended model, and
`Install-TibaTrace.ps1` performs that enrolment and the installation together.

**This model is appropriate only for terminals you control.** If TibaTrace POS is
ever distributed to the general public, buy an OV or EV certificate from a public
CA. Asking a stranger to enrol your root is asking them to trust everything you
will ever sign.

---

## Contents

| File | Purpose |
|---|---|
| `TibaTrace-POS-Setup-<version>.exe` | The signed NSIS installer |
| `tibatrace-windows-signing.cer` | The **public** signing certificate |
| `Install-TibaTrace.ps1` | Enrols the certificate, verifies, then installs |
| `SHA256SUMS.txt` | Checksums for every file above |
| `release-manifest.json` | Build provenance and signature state |
| `INSTALLATION-GUIDE.md` | This document |

The private key is **not** in this package and never leaves the signing
environment. `tibatrace-windows-signing.cer` is a public certificate: it can
verify a signature, and cannot create one.

---

## Installing

1. Copy the ZIP to the terminal and extract it.
2. Open **PowerShell as Administrator**.
3. Run:

```powershell
cd <extracted folder>
powershell -ExecutionPolicy Bypass -File .\Install-TibaTrace.ps1
```

The script will refuse to continue, and install nothing, if any of the following
does not hold:

- it is not running elevated;
- the certificate in the package does not match its pinned SHA-256;
- the certificate subject is not `CN=Esenai Group Ltd, O=Esenai Group Ltd, C=KE`;
- the certificate is outside its validity window;
- the certificate file contains a private key (it must not);
- the installer carries no signature;
- **the installer was signed by a different certificate than the one supplied**;
- the signature does not report `Valid` after enrolment.

That last-but-one check is the important one. Enrolling a certificate and then
running an installer signed by a *different* key would trust the wrong thing —
so the script pins both, and compares them.

### Verifying without installing

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-TibaTrace.ps1 -SkipInstall
```

Runs every check and stops before the installer. Useful for validating a package
before it is distributed to a fleet.

---

## What enrolment changes on the device

The public certificate is imported into two machine stores:

| Store | Why |
|---|---|
| `LocalMachine\TrustedPeople` | Marks Esenai Group as a publisher this machine accepts |
| `LocalMachine\Root` | The certificate is self-signed, so it is its own root — without this the chain still terminates untrusted and Authenticode does not report `Valid` |

`TrustedPeople` alone is not sufficient. It establishes the publisher but leaves
the chain unverifiable, which is why both are used.

Enrolling into `Root` means this device will trust **anything** signed by that
certificate from then on. That is the trade a managed fleet makes, and it is the
reason the private key is held in one place and never distributed.

---

## Verifying by hand

Before enrolment — expect a non-`Valid` status:

```powershell
Get-AuthenticodeSignature .\TibaTrace-POS-Setup-<version>.exe | Format-List Status, SignerCertificate
```

Checksum:

```powershell
Get-FileHash .\TibaTrace-POS-Setup-<version>.exe -Algorithm SHA256
```

Compare against `SHA256SUMS.txt`. The same file also verifies under
`sha256sum -c SHA256SUMS.txt` on Linux or macOS.

Certificate SHA-256, which is what the script pins:

```powershell
$c = [Security.Cryptography.X509Certificates.X509Certificate2]::new('tibatrace-windows-signing.cer')
[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($c.RawData)).Replace('-','').ToLower()
```

> `$c.Thumbprint` is SHA-1, not SHA-256. Do not pin trust to it.

---

## Removing the certificate

If a terminal leaves the fleet, or the key is ever suspected compromised:

```powershell
$sha = '<pinned SHA-256 from release-manifest.json>'
foreach ($store in 'TrustedPeople', 'Root') {
  Get-ChildItem "Cert:\LocalMachine\$store" | Where-Object {
    ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($_.RawData)).Replace('-','').ToLower()) -eq $sha
  } | Remove-Item
}
```

Uninstall TibaTrace POS separately through **Apps & features**; removing the
certificate does not remove the application.

---

## Troubleshooting

**"must be run from an elevated PowerShell session"** — right-click PowerShell
and choose *Run as administrator*. Both the machine certificate store and a
per-machine install require it.

**"Certificate does not match the pinned thumbprint"** — the package is not the
one it claims to be. Do not work around this. Re-download and, if it persists,
report it.

**"The installer was signed by a different certificate"** — the installer and the
certificate in the package do not belong together. Do not enrol the certificate.

**Signature still not `Valid` after enrolment** — usually the certificate expired,
or Group Policy is managing the root store and reverted the import. Check the
validity window shown in the script output.

**SmartScreen still warns after enrolment** — enrolment establishes trust for
signature validation; SmartScreen additionally weighs reputation, which a private
certificate does not accrue. A public OV or EV certificate is the only thing that
resolves that.
