<#
  demo/reset.ps1 - bring the demo to a clean, known state (Windows PowerShell).

    .\demo\reset.ps1                 # vulnerable stack + live dashboard (default)
    .\demo\reset.ps1 mitigated       # mitigated stack + live dashboard
    .\demo\reset.ps1 vuln -NoDashboard   # app stack only (no Grafana/Prometheus)

  Removes any existing 'app' stack, waits for a full teardown, then deploys the
  requested stack and waits until the web service is healthy.
#>
param(
    [ValidateSet('vuln','vulnerable','fixed','mitigated')]
    [string]$Mode = 'vuln',
    [switch]$NoDashboard
)
# Native commands (docker) write progress to stderr; do not treat that as a
# terminating error (PowerShell 5.1 would otherwise throw).
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$stack = 'app'
switch ($Mode) {
    { $_ -in 'vuln','vulnerable' } { $app = 'stack/vulnerable.yml' }
    { $_ -in 'fixed','mitigated' } { $app = 'stack/mitigated.yml' }
}

$files = @('-c', $app)
if (-not $NoDashboard) { $files += @('-c', 'stack/observability.yml') }

Write-Host "[reset] removing any existing '$stack' stack ..."
if (docker stack ls --format '{{.Name}}' | Select-String -Pattern "^$stack$" -Quiet) {
    docker stack rm $stack | Out-Null
}

Write-Host "[reset] waiting for teardown ..."
for ($i = 0; $i -lt 60; $i++) {
    if (-not (docker service ls --filter "name=$($stack)_" -q)) { break }
    Start-Sleep -Seconds 1
}
for ($i = 0; $i -lt 60; $i++) {
    if (-not (docker network ls --filter "name=$($stack)_iddosnet" -q)) { break }
    Start-Sleep -Seconds 1
}

if ($NoDashboard) { Write-Host "[reset] deploying: $Mode" }
else              { Write-Host "[reset] deploying: $Mode (+dashboard)" }
docker stack deploy @files $stack | Where-Object { $_ -notmatch 'detach' }

Write-Host "[reset] waiting for web to become healthy ..."
for ($i = 0; $i -lt 60; $i++) {
    $s = docker ps --filter 'label=com.docker.swarm.service.name=app_web' --format '{{.Status}}'
    if ($s -match 'healthy') { Write-Host "[reset] web is healthy: $s"; break }
    Start-Sleep -Seconds 2
}

Write-Host "[reset] done. Endpoints:"
Write-Host "          app   http://localhost:8000/work  (and /health /healthz /ready /metrics)"
Write-Host "          toxi  http://localhost:8474"
if (-not $NoDashboard) {
    Write-Host "          Grafana http://localhost:3000   Prometheus http://localhost:9090"
}
