targetScope = 'resourceGroup'

@description('Existing Azure AI Search service. This template never creates the service.')
param searchServiceName string

@description('Hosted parent and Prompt Agent runtime managed identity object ID.')
param runtimePrincipalId string

@description('Index schema management identity object ID.')
param indexManagerPrincipalId string

@description('Synthetic document ingestion identity object ID.')
param documentIngestorPrincipalId string

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

var searchIndexDataReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
var searchIndexDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var searchServiceContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')

resource runtimeReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, runtimePrincipalId, searchIndexDataReaderRole)
  scope: search
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchIndexDataReaderRole
  }
}

resource indexManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, indexManagerPrincipalId, searchServiceContributorRole)
  scope: search
  properties: {
    principalId: indexManagerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchServiceContributorRole
  }
}

resource documentIngestor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, documentIngestorPrincipalId, searchIndexDataContributorRole)
  scope: search
  properties: {
    principalId: documentIngestorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchIndexDataContributorRole
  }
}

output rbacSeparation object = {
  runtime: 'Search Index Data Reader'
  indexManager: 'Search Service Contributor'
  documentIngestor: 'Search Index Data Contributor'
}
