# download-v2-vendor.ps1
# Downloads local copies of React, ReactDOM, and Babel into service/app/static/v2/vendor/.
# Run this on the Windows production server so /v2/ can boot without outbound CDN access.
#
# Usage (from repo root or from service/):
#   powershell -ExecutionPolicy Bypass -File service\scripts\download-v2-vendor.ps1
#
# After running, redeploy or restart PZService so FastAPI serves the new vendor files.

$ErrorActionPreference = 'Stop'

$VendorDir = Join-Path $PSScriptRoot "..\app\static\v2\vendor"
$VendorDir = [System.IO.Path]::GetFullPath($VendorDir)

Write-Host "Vendor directory: $VendorDir"

$Files = @(
    @{
        Url  = "https://unpkg.com/react@18/umd/react.production.min.js"
        Dest = "react.production.min.js"
    },
    @{
        Url  = "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"
        Dest = "react-dom.production.min.js"
    },
    @{
        # PINNED to 7.x ON PURPOSE. Babel 8 changed @babel/preset-react's default JSX
        # runtime to "automatic", which injects `import { jsx } from "react/jsx-runtime"`
        # into compiled output and breaks the in-browser text/babel (classic <script>)
        # pipeline used by /v2/index.html. Keep this in lock-step with the CDN fallback
        # pin in service/app/static/v2/index.html. Guard: service/tests/test_v2_babel_pin.py.
        Url  = "https://unpkg.com/@babel/standalone@7.26.4/babel.min.js"
        Dest = "babel.min.js"
    }
)

foreach ($f in $Files) {
    $dest = Join-Path $VendorDir $f.Dest
    Write-Host "Downloading $($f.Dest) ..."
    Invoke-WebRequest -Uri $f.Url -OutFile $dest -UseBasicParsing
    $size = (Get-Item $dest).Length
    Write-Host "  -> $dest ($size bytes)"
}

Write-Host ""
Write-Host "Done. Vendor files are ready."
Write-Host "Restart PZService (or robocopy deploy) so the new files are served."
