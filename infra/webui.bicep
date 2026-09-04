targetScope = 'resourceGroup'

@description('Globally unique Linux App Service name.')
param webAppName string

@description('App Service Plan name.')
param appServicePlanName string

@description('Serverless Developer Azure AI Search name; availability must be checked before apply.')
param searchServiceName string

@description('Existing Foundry project endpoint; this value is not secret.')
param foundryProjectEndpoint string

@description('Hosted parent agent name.')
param hostedParentAgentName string = 'procurement-parent-agent'

param location string = resourceGroup().location
param searchLocation string = 'westcentralus'
param apimName string
param apimLocation string = 'eastus'
@secure()
param apimPublisherEmail string
param entraClientId string
@secure()
param entraClientSecret string
@secure()
@minLength(32)
param sessionSigningKey string
param foundryAccountName string = 'observability-verify'
param foundryProjectName string = 'proj-default'

var proxyEndpoint = 'https://${apimName}.azure-api.net/foundry/proj-default'

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${webAppName}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${webAppName}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource webApp 'Microsoft.Web/sites@2024-04-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      linuxFxVersion: 'PYTHON|3.13'
      appCommandLine: 'bash startup.sh'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'PROJECT_ENDPOINT'
          value: proxyEndpoint
        }
        {
          name: 'AGENT_NAME'
          value: hostedParentAgentName
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        { name: 'WEB_APP_URL', value: 'https://${webAppName}.azurewebsites.net' }
        { name: 'WEBUI_SESSION_SIGNING_KEY', value: sessionSigningKey }
        { name: 'ENTRA_CLIENT_SECRET', value: entraClientSecret }
        { name: 'OTEL_PROPAGATORS', value: 'tracecontext,baggage' }
        { name: 'OTEL_TRACES_SAMPLER', value: 'always_on' }
        { name: 'ENABLE_SENSITIVE_DATA', value: 'false' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
      ]
    }
  }
}

resource auth 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: webApp
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true, runtimeVersion: '~1' }
    globalValidation: { requireAuthentication: true, unauthenticatedClientAction: 'RedirectToLoginPage', redirectToProvider: 'azureactivedirectory' }
    httpSettings: { requireHttps: true }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: 'ENTRA_CLIENT_SECRET'
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: { allowedAudiences: [entraClientId] }
      }
    }
    login: { tokenStore: { enabled: false } }
  }
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}
resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundryAccount
  name: foundryProjectName
}
// Runtime only; Conversations authorization must be measured with the Web MI.
resource foundryInvoker 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryProject.id, webApp.id, 'foundry-invoker')
  scope: foundryProject
  properties: {
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '142bfaed-a13f-4c2d-bed2-6db62c4a1009')
  }
}

module apim 'apim.bicep' = {
  name: 'procurement-apim'
  params: {
    name: apimName
    location: apimLocation
    publisherEmail: apimPublisherEmail
    projectEndpoint: foundryProjectEndpoint
    webAppPrincipalId: webApp.identity.principalId
    agentName: hostedParentAgentName
    instrumentationKey: appInsights.properties.InstrumentationKey
  }
}

resource search 'Microsoft.Search/searchServices@2026-03-01-preview' = {
  name: searchServiceName
  location: searchLocation
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'serverless'
  }
  properties: {
    publicNetworkAccess: 'enabled'
    disableLocalAuth: true
  }
}

output webAppId string = webApp.id
output webAppHostName string = webApp.properties.defaultHostName
output webAppPrincipalId string = webApp.identity.principalId
output appInsightsResourceId string = appInsights.id
output searchServiceId string = search.id
output apimResourceId string = apim.outputs.gatewayId
