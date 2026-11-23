# One-step ship to the Azure demo: deploy the code, then check the live site.
#
#   .\infra\ship.ps1            # or double-click ship.cmd
#
# Demo open access (blank-PIN sign-in) is NOT part of this. Flip it in the app: Admin -> Access.
param(
    [string]$ResourceGroup = "rg-solstice-demo",
    [string]$App = "ca-solstice-web"
)
$ErrorActionPreference = "Stop"

Write-Host "== Deploying code ==" -ForegroundColor Cyan
& "$PSScriptRoot\deploy.ps1" -ResourceGroup $ResourceGroup -App $App

Write-Host "== Checking the live site ==" -ForegroundColor Cyan
$url = "https://" + (az containerapp show -g $ResourceGroup -n $App --query properties.configuration.ingress.fqdn -o tsv)
$page = $null
foreach ($i in 1..12) {   # a fresh revision can take a minute to answer
    try { $page = (Invoke-WebRequest "$url/admin" -UseBasicParsing -TimeoutSec 30).Content; break } catch { Start-Sleep -Seconds 10 }
}
if (-not $page) { throw "The site did not answer at $url/admin." }
$open = $page -match 'data-open-access="true"'
$theme = [regex]::Match($page, 'data-theme="([^"]+)"').Groups[1].Value
Write-Host "Site:            $url"
Write-Host "Theme:           $theme"
Write-Host ("Open access:     " + $(if ($open) { "ON (blank PIN works for staff and admin)" } else { "off (PIN required)" }))
Write-Host "Image:           $(az containerapp show -g $ResourceGroup -n $App --query 'properties.template.containers[0].image' -o tsv)"
Write-Host "Done." -ForegroundColor Green
