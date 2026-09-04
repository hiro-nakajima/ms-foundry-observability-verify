targetScope = 'resourceGroup'

param storageAccountName string = 'stprocurementobsnkjm'
param location string = 'westcentralus'
param searchPrincipalId string
param ingestorPrincipalId string

resource storage 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  tags: { purpose: 'procurement-synthetic-indexer-poc' }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

var containerNames = ['procurement-catalog', 'procurement-code-master']
var readerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
var writerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = [for name in containerNames: {
  parent: blobs
  name: name
  properties: { publicAccess: 'None' }
}]

resource readers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (name, i) in containerNames: {
  name: guid(containers[i].id, searchPrincipalId, readerRole)
  scope: containers[i]
  properties: {
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: readerRole
  }
}]

resource writers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (name, i) in containerNames: {
  name: guid(containers[i].id, ingestorPrincipalId, writerRole)
  scope: containers[i]
  properties: {
    principalId: ingestorPrincipalId
    principalType: 'User'
    roleDefinitionId: writerRole
  }
}]

output storageId string = storage.id
