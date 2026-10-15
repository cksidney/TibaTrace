# Check the actual PE icon resources rather than only the builder configuration.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$expectedPath = (Resolve-Path 'apps/pos-windows/public/brand/tibatrace.ico').Path
$version = (Get-Content apps/pos-windows/package.json | ConvertFrom-Json).version
$expectedIcon = [System.Drawing.Icon]::new($expectedPath, 32, 32)
$expected = $expectedIcon.ToBitmap()
try {
  foreach ($path in @('apps/pos-windows/release/win-unpacked/TibaTrace POS.exe', "apps/pos-windows/release/TibaTrace-POS-Setup-$version.exe")) {
    $actualIcon = [System.Drawing.Icon]::ExtractAssociatedIcon((Resolve-Path $path).Path)
    if (-not $actualIcon) { throw "Missing icon: $path" }
    $actual = $actualIcon.ToBitmap()
    try {
      if ($actual.Width -ne 32 -or $actual.Height -ne 32) { throw "Unexpected icon dimensions: $path" }
      $different = 0
      for ($x = 0; $x -lt 32; $x++) {
        for ($y = 0; $y -lt 32; $y++) {
          $a = $actual.GetPixel($x, $y); $e = $expected.GetPixel($x, $y)
          if ($a.A -eq 0 -and $e.A -eq 0) { continue }
          if ($a.ToArgb() -ne $e.ToArgb()) { $different++ }
        }
      }
      # Allow small Windows alpha-rendering differences; Electron's atom icon
      # does not resemble this reference and fails this comparison.
      if ($different -gt 51) { throw "Executable does not carry the TibaTrace logo: $path ($different pixels differ)" }
      Write-Host "TibaTrace PE branding verified: $path"
    } finally { $actual.Dispose(); $actualIcon.Dispose() }
  }
} finally { $expected.Dispose(); $expectedIcon.Dispose() }
