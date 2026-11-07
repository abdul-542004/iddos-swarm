<#
  demo/detect.ps1 - run the live detector so the audience sees alerts.

    .\demo\detect.ps1              # run until Ctrl+C
    .\demo\detect.ps1 --duration 150

  Streams health events + restart counts and raises alerts, naming the cause
  (dependency latency, not a crash). Also appended to results/alerts.log.
#>
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
python detector/monitor.py @args
