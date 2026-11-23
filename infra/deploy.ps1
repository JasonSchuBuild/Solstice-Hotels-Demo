# Ship the current local code to the Azure demo in one step.
#
#   .\infra\deploy.ps1            # tag = timestamp
#   .\infra\deploy.ps1 -Tag v5
#
# Builds the image in Azure Container Registry (no local Docker), points the container app
# at it, then turns off the previous revision. That last step works around new revisions
# sometimes staying "Activating" while the old one keeps serving (seen twice on 2026-11-18).
# Roll back: az containerapp revision activate -g rg-solstice-demo -n ca-solstice-web --revision <old-name>
param(
    [string]$Tag = "v" + (Get-Date -Format "yyyyMMdd-HHmm"),
    [string]$ResourceGroup = "rg-solstice-demo",
    [string]$App = "ca-solstice-web"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$acr = az acr list -g $ResourceGroup --query "[0].name" -o tsv
$server = az acr show -n $acr --query loginServer -o tsv

Write-Host "1/4 Building $acr/solstice-web:$Tag in Azure..."
az acr build --registry $acr --image "solstice-web:$Tag" --file "$root\Dockerfile" $root --no-logs --query status -o tsv
if ($LASTEXITCODE -ne 0) { throw "Image build failed." }

$old = az containerapp revision list -g $ResourceGroup -n $App --query "[?properties.active].name" -o tsv
Write-Host "2/4 Rolling $App to $Tag..."
$new = az containerapp update -g $ResourceGroup -n $App --image "$server/solstice-web:$Tag" --query properties.latestRevisionName -o tsv
if ($LASTEXITCODE -ne 0) { throw "Update failed." }

Write-Host "3/4 Waiting for $new to start..."
$url = "https://" + (az containerapp show -g $ResourceGroup -n $App --query properties.configuration.ingress.fqdn -o tsv)
Start-Sleep -Seconds 20
foreach ($r in ($old -split "`n" | Where-Object { $_ -and $_ -ne $new })) {
    az containerapp revision deactivate -g $ResourceGroup -n $App --revision $r -o none
    Write-Host "    turned off old revision $r"
}

Write-Host "4/4 Checking $url/healthz ..."
$ok = $false
foreach ($i in 1..12) {
    try { if ((Invoke-RestMethod "$url/healthz" -TimeoutSec 20).status -eq "ok") { $ok = $true; break } } catch {}
    Start-Sleep -Seconds 10
}
az containerapp revision list -g $ResourceGroup -n $App --query "[].{revision:name, health:properties.healthState, traffic:properties.trafficWeight, image:properties.template.containers[0].image}" -o table
if ($ok) { Write-Host "Live: $url" } else { throw "Health check did not pass; see the revision list above." }
