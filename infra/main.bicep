// Solstice demo on Azure: Container Apps + Key Vault + Container Registry + Log Analytics/App Insights.
// Deployed in two phases (see infra/README.md):
//   1. deployApp=false  -> identity, registry, vault, logs, Container Apps environment
//   2. deployApp=true   -> the container app (after the image is built and the API key is in Key Vault)

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short name used in resource names.')
param appName string = 'solstice'

@description('Object ID of the person deploying (gets permission to write the API key into Key Vault).')
param deployerObjectId string

@description('Create the container app (phase 2).')
param deployApp bool = false

@description('Image tag in the registry, e.g. solstice-web:v1.')
param image string = 'solstice-web:v1'

@description('Time zone for the warm windows (IANA name).')
param warmTimezone string = 'America/Los_Angeles'

// Keep one instance running 6am-6pm Pacific (warmTimezone) every day from Nov 20 to Dec 14, 2026 (no cold start for demos),
// then let the app scale back to zero on its own. Cron can't express a year, so these repeat every
// Nov 20-30 / Dec 1-14 until the rules are removed: delete this list (or set it to []) after the demo season.
// Cost while warm: about $0.40 a day idle. Fields: minute hour day-of-month month day-of-week.
var warmWindows = [
  { start: '0 6 20-30 11 *', end: '0 18 20-30 11 *' }
  { start: '0 6 1-14 12 *', end: '0 18 1-14 12 *' }
]

// Scale rules: live traffic keeps the replica up (http), and the warm windows keep it up when idle (cron).
var warmRules = [for (w, i) in warmWindows: {
  name: 'warm-${i}'
  custom: {
    type: 'cron'
    metadata: {
      timezone: warmTimezone
      start: w.start
      end: w.end
      desiredReplicas: '1'
    }
  }
  }]
var scaleRules = concat([ { name: 'http', http: { metadata: { concurrentRequests: '20' } } } ], warmRules)

var suffix = uniqueString(resourceGroup().id)
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var kvSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var kvSecretsOfficer = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var blobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var tags = { project: 'solstice-agent-demo' }

// The app's identity: pulls the image and reads the API key. No passwords anywhere.
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${appName}-${suffix}'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${appName}-${suffix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${appName}-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${appName}${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${take(appName, 6)}-${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
  }
}

// Small durable store for admin-chosen settings (the website theme). The container's own disk is wiped
// on every restart and the app scales to zero, so settings can't live there. Identity-only access: no keys.
resource settingsStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${take(appName, 8)}${take(suffix, 13)}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource settingsBlobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: settingsStorage
  name: 'default'
}

resource settingsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: settingsBlobs
  name: 'solstice-settings'
}

resource settingsWriteRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(settingsStorage.id, identity.id, blobDataContributor)
  scope: settingsStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvReadRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, identity.id, kvSecretsUser)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvDeployerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, deployerObjectId, kvSecretsOfficer)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsOfficer)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${appName}-${suffix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [ { name: 'Consumption', workloadProfileType: 'Consumption' } ]
  }
}

resource app 'Microsoft.App/containerApps@2026-07-01' = if (deployApp) {
  name: 'ca-${appName}-web'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [ { server: acr.properties.loginServer, identity: identity.id } ]
      secrets: [
        {
          name: 'anthropic-api-key'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/anthropic-api-key'
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: '${acr.properties.loginServer}/${image}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            // Where the admin-chosen theme is saved (themes.py). AZURE_CLIENT_ID picks the managed identity.
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: settingsStorage.properties.primaryEndpoints.blob }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 10 }
          ]
        }
      ]
      // Sessions live in memory, so one replica max. Scale to zero when idle, except inside the warm windows below.
      // The http rule matters: with only cron rules, KEDA ignores live traffic and scaled the app back to zero
      // ~5 minutes after any wake-up outside a window, mid-conversation (seen 2026-11-23, 04:02-04:18 UTC), which
      // wiped every chat. cooldownPeriod = the 30-minute session idle timeout (sessions.py), so the replica outlives
      // any chat that is still in use.
      scale: {
        minReplicas: 0
        maxReplicas: 1
        cooldownPeriod: 1800
        rules: scaleRules
      }
    }
  }
  dependsOn: [ acrPullRole, kvReadRole, settingsWriteRole, settingsContainer ]
}

output registryName string = acr.name
output registryServer string = acr.properties.loginServer
output keyVaultName string = kv.name
output appUrl string = deployApp ? 'https://${app!.properties.configuration.ingress.fqdn}' : ''
