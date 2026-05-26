// Foundry Retirement Monitor — AKS infrastructure
// 一切命名采用语义化前缀；ACR 名字受全局唯一约束（仅小写字母数字），
// 通过参数 `acrName` 提供。若被占用，请在 main.parameters.json 改名。

targetScope = 'resourceGroup'

@description('Azure region。')
param location string = resourceGroup().location

@description('AKS 集群名。')
param aksName string = 'aks-foundry-monitor'

@description('Application Gateway 名。')
param appGwName string = 'agw-foundry-monitor'

@description('VNet 名。')
param vnetName string = 'vnet-foundry-monitor'

@description('Log Analytics Workspace 名。')
param logWorkspaceName string = 'log-foundry-monitor'

@description('ACR 名（全局唯一，只允许小写字母数字，5-50 字符）。如被占用请改。')
@minLength(5)
@maxLength(50)
param acrName string = 'acrfoundrymonitor'

@description('AKS 系统节点池 VM SKU。Standard_D2s_v5 是最小可用规格。')
param nodeVmSize string = 'Standard_D2s_v5'

@description('AKS 节点数。')
param nodeCount int = 2

@description('Kubernetes 版本（留空使用区域默认）。')
param kubernetesVersion string = ''

var tags = {
  project: 'foundry-retirement-monitor'
  managedBy: 'bicep'
}

// ---------------- 网络 ----------------
resource appGwNsg 'Microsoft.Network/networkSecurityGroups@2024-01-01' = {
  name: 'nsg-snet-appgw'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowHttpsInbound'
        properties: {
          priority: 100
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowHttpInbound'
        properties: {
          priority: 110
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '80'
        }
      }
      {
        name: 'AllowGatewayManagerInbound'
        properties: {
          priority: 200
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: 'GatewayManager'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '65200-65535'
        }
      }
      {
        name: 'AllowAzureLoadBalancerInbound'
        properties: {
          priority: 210
          access: 'Allow'
          direction: 'Inbound'
          protocol: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.30.0.0/16'] }
    subnets: [
      {
        name: 'snet-aks'
        properties: { addressPrefix: '10.30.0.0/22' }
      }
      {
        name: 'snet-appgw'
        properties: {
          addressPrefix: '10.30.4.0/24'
          networkSecurityGroup: { id: appGwNsg.id }
        }
      }
    ]
  }
}

resource subnetAks 'Microsoft.Network/virtualNetworks/subnets@2024-01-01' existing = {
  parent: vnet
  name: 'snet-aks'
}
resource subnetAppGw 'Microsoft.Network/virtualNetworks/subnets@2024-01-01' existing = {
  parent: vnet
  name: 'snet-appgw'
}

// ---------------- Application Gateway 公网 IP ----------------
resource appGwPip 'Microsoft.Network/publicIPAddresses@2024-01-01' = {
  name: 'pip-agw-foundry-monitor'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: {
      domainNameLabel: 'foundry-monitor'
    }
  }
}

// ---------------- Application Gateway v2 (Standard_v2) ----------------
// AGIC 会在部署后接管 listener/backend/rules 等配置；这里只提供最小骨架。
resource appGw 'Microsoft.Network/applicationGateways@2024-01-01' = {
  name: appGwName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'Standard_v2'
      tier: 'Standard_v2'
    }
    autoscaleConfiguration: {
      minCapacity: 1
      maxCapacity: 2
    }
    gatewayIPConfigurations: [
      {
        name: 'gwip'
        properties: { subnet: { id: subnetAppGw.id } }
      }
    ]
    frontendIPConfigurations: [
      {
        name: 'feip-public'
        properties: { publicIPAddress: { id: appGwPip.id } }
      }
    ]
    frontendPorts: [
      { name: 'port80', properties: { port: 80 } }
    ]
    backendAddressPools: [
      { name: 'pool-default', properties: {} }
    ]
    backendHttpSettingsCollection: [
      {
        name: 'http-default'
        properties: {
          port: 80
          protocol: 'Http'
          cookieBasedAffinity: 'Disabled'
          requestTimeout: 30
        }
      }
    ]
    httpListeners: [
      {
        name: 'listener-default'
        properties: {
          frontendIPConfiguration: { id: resourceId('Microsoft.Network/applicationGateways/frontendIPConfigurations', appGwName, 'feip-public') }
          frontendPort: { id: resourceId('Microsoft.Network/applicationGateways/frontendPorts', appGwName, 'port80') }
          protocol: 'Http'
        }
      }
    ]
    requestRoutingRules: [
      {
        name: 'rule-default'
        properties: {
          ruleType: 'Basic'
          priority: 100
          httpListener: { id: resourceId('Microsoft.Network/applicationGateways/httpListeners', appGwName, 'listener-default') }
          backendAddressPool: { id: resourceId('Microsoft.Network/applicationGateways/backendAddressPools', appGwName, 'pool-default') }
          backendHttpSettings: { id: resourceId('Microsoft.Network/applicationGateways/backendHttpSettingsCollection', appGwName, 'http-default') }
        }
      }
    ]
  }
}

// ---------------- ACR ----------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

// ---------------- Log Analytics ----------------
resource logws 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logWorkspaceName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ---------------- AKS Standard with AGIC + Monitoring ----------------
resource aks 'Microsoft.ContainerService/managedClusters@2024-05-01' = {
  name: aksName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    kubernetesVersion: empty(kubernetesVersion) ? null : kubernetesVersion
    dnsPrefix: aksName
    enableRBAC: true
    agentPoolProfiles: [
      {
        name: 'sys'
        mode: 'System'
        count: nodeCount
        vmSize: nodeVmSize
        osType: 'Linux'
        osDiskSizeGB: 64
        vnetSubnetID: subnetAks.id
        type: 'VirtualMachineScaleSets'
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      networkPolicy: 'azure'
      serviceCidr: '10.40.0.0/16'
      dnsServiceIP: '10.40.0.10'
      loadBalancerSku: 'standard'
    }
    addonProfiles: {
      ingressApplicationGateway: {
        enabled: true
        config: {
          applicationGatewayId: appGw.id
        }
      }
      omsagent: {
        enabled: true
        config: {
          logAnalyticsWorkspaceResourceID: logws.id
        }
      }
    }
  }
}

// ---------------- RBAC: AKS kubelet -> ACR pull ----------------
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull

resource roleAksAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, aks.id, acrPullRoleId)
  properties: {
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

// ---------------- RBAC: AGIC identity 操作 AppGw 所在 RG ----------------
// AGIC addon 会创建一个 user-assigned identity，需要在 AppGw 的 RG 上获得 Contributor
// 以及在 AppGw 资源上获得 Reader / Contributor。最小化：在 AppGw 上授 Contributor。
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

resource roleAgicOnAppGw 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appGw
  name: guid(appGw.id, aks.id, 'agic-contrib')
  properties: {
    principalId: aks.properties.addonProfiles.ingressApplicationGateway.identity.objectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource roleAgicOnRg 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: resourceGroup()
  name: guid(resourceGroup().id, aks.id, 'agic-reader')
  properties: {
    principalId: aks.properties.addonProfiles.ingressApplicationGateway.identity.objectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalType: 'ServicePrincipal'
  }
}

// AGIC 还需要在 AppGw 所在 VNet 上 Network Contributor，否则会报
// ApplicationGatewayInsufficientPermissionOnSubnet。
var networkContributorRoleId = '4d97b98b-1d4f-4787-a291-c67834d212e7'

resource roleAgicOnVnet 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vnet
  name: guid(vnet.id, aks.id, 'agic-net-contrib')
  properties: {
    principalId: aks.properties.addonProfiles.ingressApplicationGateway.identity.objectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', networkContributorRoleId)
    principalType: 'ServicePrincipal'
  }
}

output acrLoginServer string = acr.properties.loginServer
output aksClusterName string = aks.name
output appGwPublicIp string = appGwPip.properties.ipAddress
output appGwFqdn string = appGwPip.properties.dnsSettings.fqdn
output resourceGroupName string = resourceGroup().name
