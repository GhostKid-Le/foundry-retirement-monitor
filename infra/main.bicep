targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd environment name; used as resource prefix')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Cron schedule (NCRONTAB, in WEBSITE_TIME_ZONE) — default: 08:30 every day')
param scheduleCron string = '0 30 8 * * *'

@description('Time zone for the timer trigger (Windows TZ ID)')
param timeZone string = 'China Standard Time'

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  app: 'foundry-retirement-monitor'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    resourceToken: resourceToken
    tags: tags
    scheduleCron: scheduleCron
    timeZone: timeZone
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_FUNCTION_NAME string = resources.outputs.functionAppName
output AZURE_STORAGE_ACCOUNT string = resources.outputs.storageAccountName
