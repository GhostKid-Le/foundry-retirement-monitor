param location string
param resourceToken string
param tags object
param scheduleCron string
param timeZone string

var abbrs = loadJsonContent('./abbreviations.json')

// ---------------- User-assigned Managed Identity ----------------
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${abbrs.managedIdentityUserAssignedIdentities}${resourceToken}'
  location: location
  tags: tags
}

// ---------------- Storage (Function host + history blob) ----------------
resource storage 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  #disable-next-line BCP334
  name: '${abbrs.storageStorageAccounts}${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    // MI is used everywhere; shared keys disabled for hardening.
    allowSharedKeyAccess: false
    // Flex Consumption host pulls the deployment package over public network
    // (no private endpoint configured). Keep this Enabled or the function host
    // fails with "Service is unavailable".
    publicNetworkAccess: 'Enabled'
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: storage
  name: 'default'
}

resource historyContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobServices
  name: 'history'
  properties: {
    publicAccess: 'None'
  }
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobServices
  name: 'deploymentpackage'
  properties: {
    publicAccess: 'None'
  }
}

// ---------------- Log Analytics + Application Insights ----------------
resource logws 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: '${abbrs.insightsComponents}${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logws.id
  }
}

// ---------------- Communication Services / Email ----------------
// 已废弃：邮件发送已迁移到 Power Automate webhook（见 README）。
// 历史版本曾在此 provision ACS + Email Service + AzureManagedDomain，
// 现已移除；如需回滚，请查 git history。

// ---------------- App Service Plan (Flex Consumption) ----------------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${abbrs.webServerFarms}${resourceToken}'
  location: location
  tags: tags
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  kind: 'functionapp,linux'
  properties: {
    reserved: true
  }
}

// ---------------- Function App (Flex Consumption + Managed Identity) ----------------
resource func 'Microsoft.Web/sites@2024-04-01' = {
  name: '${abbrs.webSitesFunctions}${resourceToken}'
  location: location
  kind: 'functionapp,linux'
  tags: union(tags, { 'azd-service-name': 'func' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainer.name}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: uami.id
          }
        }
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
      scaleAndConcurrency: {
        instanceMemoryMB: 2048
        maximumInstanceCount: 40
      }
    }
    siteConfig: {
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storage.name
        }
        {
          name: 'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name: 'AzureWebJobsStorage__clientId'
          value: uami.properties.clientId
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appi.properties.ConnectionString
        }
        {
          name: 'WEBSITE_TIME_ZONE'
          value: timeZone
        }
        {
          name: 'SCHEDULE_CRON'
          value: scheduleCron
        }
        {
          name: 'AZURE_CLIENT_ID'
          value: uami.properties.clientId
        }
        {
          name: 'STORAGE_ACCOUNT_NAME'
          value: storage.name
        }
        {
          name: 'HISTORY_CONTAINER'
          value: historyContainer.name
        }
        {
          name: 'HISTORY_BLOB'
          value: 'foundry_retirement_history.json'
        }
        {
          name: 'SOURCE_URL'
          value: 'https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule'
        }
        {
          name: 'WINDOW_DAYS'
          value: '30'
        }
        // MAILER_WEBHOOK_URL: Power Automate trigger URL；由部署后手工写入
        // （含 '&' 字符，需用 `az rest PUT /config/appsettings` 而非 `az functionapp config appsettings set`）。
        // 详见 README.md 第 3 步。
      ]
    }
  }
}

// ---------------- RBAC: UAMI -> Storage roles (MI access for runtime + deployment) ----------------
var blobOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'   // Storage Blob Data Owner
var queueContribRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // Storage Queue Data Contributor
var tableContribRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3' // Storage Table Data Contributor

resource roleStorageBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, uami.id, blobOwnerRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobOwnerRoleId)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource roleStorageQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, uami.id, queueContribRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueContribRoleId)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource roleStorageTable 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, uami.id, tableContribRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', tableContribRoleId)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output functionAppName string = func.name
output storageAccountName string = storage.name
output userAssignedIdentityClientId string = uami.properties.clientId
