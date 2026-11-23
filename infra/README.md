# Deploying to Azure

Azure Container Apps + Key Vault + Container Registry + Log Analytics / Application Insights.
Why this platform: `docs/ARCHITECTURE.md` → Hosting decision.

All commands run from the repo root in PowerShell, signed in with `az login`.

## Resources (resource group `rg-solstice-demo`, region `eastus2`)

| Resource | Purpose |
|---|---|
| User-assigned managed identity | The app's identity: pulls the image, reads the API key. No passwords. |
| Container Registry (Basic) | Holds the app image. Admin user disabled. |
| Key Vault (RBAC) | Holds `anthropic-api-key`. The app reads it by identity. |
| Log Analytics + Application Insights | Container logs and telemetry. |
| Storage account (Standard LRS, no keys) | Small blobs in the `solstice-settings` container holding the admin-chosen settings (website theme `theme.json`, demo open access `open_access.json`), so they survive restarts, scale-to-zero and redeploys. The app writes it with its managed identity (Storage Blob Data Contributor). |
| Container Apps environment + app | Runs the web app. Consumption plan, scales to zero, max 1 replica. |

## One-time setup

```powershell
foreach ($ns in "Microsoft.App","Microsoft.ContainerRegistry","Microsoft.KeyVault","Microsoft.ManagedIdentity","Microsoft.OperationalInsights","Microsoft.Insights") { az provider register --namespace $ns }
az bicep install
az group create --name rg-solstice-demo --location eastus2
```

## Phase 1: base infrastructure

```powershell
$me = az ad signed-in-user show --query id -o tsv
az deployment group create -g rg-solstice-demo -f infra/main.bicep -p deployerObjectId=$me deployApp=false
```

## Build the image (in Azure, no local Docker needed)

```powershell
$acr = az deployment group show -g rg-solstice-demo -n main --query properties.outputs.registryName.value -o tsv
az acr build --registry $acr --image solstice-web:v1 .
```

`.dockerignore` is an allow-list, so `.env`, `_private/`, docs and tests never leave your machine.

## Store the API key (run this yourself)

Reads the key from `.env` and writes it to Key Vault without printing it:

```powershell
$kv = az deployment group show -g rg-solstice-demo -n main --query properties.outputs.keyVaultName.value -o tsv
$key = ((Get-Content .env | Select-String '^ANTHROPIC_API_KEY=').Line -split '=', 2)[1]
az keyvault secret set --vault-name $kv --name anthropic-api-key --value $key --output none; Remove-Variable key
```

## Phase 2: the container app

```powershell
az deployment group create -g rg-solstice-demo -f infra/main.bicep -p deployerObjectId=$me deployApp=true image=solstice-web:v1
az deployment group show -g rg-solstice-demo -n main --query properties.outputs.appUrl.value -o tsv
```

## Updating the app

One step (build, roll out, turn off the old revision, health check):

```powershell
.\infra\deploy.ps1
```

Manual equivalent (Bicep, also applies infrastructure changes):

```powershell
az acr build --registry $acr --image solstice-web:v2 .
az deployment group create -g rg-solstice-demo -f infra/main.bicep -p deployerObjectId=$me deployApp=true image=solstice-web:v2
```

Check the new revision is serving, not just deployed:

```powershell
az containerapp revision list -g rg-solstice-demo -n ca-solstice-web --query "[].{name:name, health:properties.healthState, running:properties.runningState, traffic:properties.trafficWeight}" -o table
```

Seen on 2026-11-18: the new revision started and passed its probes but stayed "Activating" while the old one kept serving. Fix: deactivate the old revision (`az containerapp revision deactivate -g rg-solstice-demo -n ca-solstice-web --revision <old-name>`); `revision activate` brings it back if needed.

## Scheduled warm windows

`main.bicep` has a `warmWindows` list: cron rules that keep one instance running 6am–6pm (`warmTimezone`, default America/Los_Angeles, Pacific time) every day from Nov 20 to Dec 14, 2026. Outside the windows the app scales to zero as usual, so nothing needs turning off. Cron can't hold a year, so the rules would repeat each Nov 20–Dec 14: set `warmWindows` to `[]` (or edit the dates) and redeploy after the demo season. Apply changes with the phase 2 Bicep command, using the image tag that's currently running.

**Outside a window**, the first request wakes the app (a 30–60 s cold start), and it then stays up for 30 minutes after the last request (`cooldownPeriod: 1800` plus an `http` scale rule in `main.bicep`). Before 2026-11-23 there was no HTTP rule, so KEDA scaled the app back to zero about 5 minutes after every wake-up, mid-conversation, which wiped the in-memory chats.

## Before a demo: live smoke test

Runs the demo scenarios against the live site (about 15 model turns, a few cents) and ends with DEMO-READY or the failures. Staff, group sales and admin run only with a PIN in the environment (or with demo open access on); otherwise they're skipped.

```powershell
cd backend
$env:SOLSTICE_SMOKE_PIN = "<staff pin>"; $env:SOLSTICE_SMOKE_ADMIN_PIN = "<admin pin>"
.\.venv\Scripts\python.exe ..\infra\smoke_test.py
```

It leaves a few test tickets in the staff console until the app next scales to zero, and it uses about 15 of the 20 messages per 10 minutes allowed per address, so run it at least 10 minutes before demoing from the same network.

## Demo day (manual override)

Avoid the cold start by keeping one instance running, then turn it back off afterwards:

```powershell
az containerapp update -g rg-solstice-demo -n ca-solstice-web --min-replicas 1   # before
az containerapp update -g rg-solstice-demo -n ca-solstice-web --min-replicas 0   # after
```

## Cost guardrail

Subscription budget `solstice-monthly-25`: $25/month, email alerts at 50%, 80% and 100% of actual spend, and when the month is forecast to exceed $25. Alerts only notify; they don't stop resources. Expected demo spend is a few dollars a month (registry, logs, tokens). The usual cause of a surprise is leaving `--min-replicas 1` on after a demo.

```powershell
az consumption budget show --budget-name solstice-monthly-25
```

## Tear down

```powershell
az group delete --name rg-solstice-demo
```

Key Vault is soft-deleted for 7 days after this; the same name can't be reused until it's purged.

## Website theme (persistent)

Admin → Appearance saves the theme to Blob Storage when `AZURE_STORAGE_ACCOUNT_URL` is set (Bicep sets it); locally it's `data/runtime/theme.json`. If the storage is unreachable the site shows the default theme rather than failing. This release added the storage account, so apply it once with Bicep (phase 2 command above) before `deploy.ps1`, which only swaps the image.

## Shipping and demo access

Double-click `infra/ship.cmd` (or run `.\infra\ship.ps1`) to deploy the code and check the live site. Blank-PIN sign-in for live demos is not a deploy: flip it in the app at Admin → Access, instantly, with no restart. It's off by default; `access.allow_open_access` in `config/settings.yaml` is the master switch.

## Notes

- The website theme and demo open access are the only admin-written settings, and they are the only things persisted outside the container (Blob Storage). Tickets, traces and the audit log are written inside the container and are lost on restart. Production writes them to a database / Application Insights.
- Sessions are in memory, which is why the app is capped at one replica.
- The demo PINs still come from `config/settings.yaml`. Production replaces them with Entra ID sign-in (`docs/ACCESS_CONTROL.md`).
