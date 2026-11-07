<#
  demo/attack.ps1 - the one attack action: add (or remove) the latency toxic.

    .\demo\attack.ps1            # add a 5000ms latency toxic (start the attack)
    .\demo\attack.ps1 8000       # add an 8000ms latency toxic
    .\demo\attack.ps1 off        # remove the toxic (stop the attack)

  The attacker only slows the database path through Toxiproxy. The web
  container is never touched.
#>
param([string]$Arg = '')
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Arg -eq 'off') {
    python attack/inject_latency.py remove
    Write-Host "[attack] toxic removed - watch the service recover."
}
else {
    $lat = if ($Arg) { $Arg } else { '5000' }
    python attack/inject_latency.py add --latency $lat | Out-Null
    Write-Host "[attack] latency ${lat}ms injected on the database path."
    Write-Host "[attack] watch: restart count climbing, availability falling, /work still works in the app log."
    Write-Host "[attack] stop with:  .\demo\attack.ps1 off"
}
