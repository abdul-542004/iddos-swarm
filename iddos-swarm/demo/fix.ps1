<#
  demo/fix.ps1 - apply the mitigation: redeploy with the mitigated stack.

    .\demo\fix.ps1

  Swaps the vulnerable stack for the mitigated one (liveness-only health-check
  + tuned restart policy). The dashboard stays up. After this, run the SAME
  attack again and watch the service stay available.
#>
$ErrorActionPreference = 'Continue'
Write-Host "[fix] switching to the mitigated stack ..."
& (Join-Path $PSScriptRoot 'reset.ps1') mitigated
