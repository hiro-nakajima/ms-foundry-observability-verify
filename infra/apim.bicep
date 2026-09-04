targetScope = 'resourceGroup'

param name string
param location string = 'eastus'
@allowed(['Developer', 'Consumption'])
param skuName string = 'Developer'
@secure()
param publisherEmail string
param projectEndpoint string
param webAppPrincipalId string
param agentName string = 'procurement-parent-agent'
@secure()
param instrumentationKey string

resource gateway 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: name
  location: location
  sku: { name: skuName, capacity: skuName == 'Consumption' ? 0 : 1 }
  properties: {
    publisherName: 'Procurement Observability PoC'
    publisherEmail: publisherEmail
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: gateway
  name: 'foundry-proj-default'
  properties: {
    displayName: 'Procurement Foundry project'
    path: 'foundry/proj-default'
    protocols: ['https']
    serviceUrl: projectEndpoint
    subscriptionRequired: false
  }
}

// No wildcard agent selector, admin APIs, delete operation or Graph/OBO path.
var routes = [
  { name: 'create-conversation', method: 'POST', url: '/agents/${agentName}/endpoint/protocols/openai/conversations', parameters: [] }
  { name: 'get-conversation', method: 'GET', url: '/agents/${agentName}/endpoint/protocols/openai/conversations/{conversation}', parameters: [{ name: 'conversation', type: 'string', required: true }] }
  { name: 'update-conversation', method: 'POST', url: '/agents/${agentName}/endpoint/protocols/openai/conversations/{conversation}', parameters: [{ name: 'conversation', type: 'string', required: true }] }
  { name: 'parent-response', method: 'POST', url: '/agents/${agentName}/endpoint/protocols/openai/responses', parameters: [] }
]

resource operations 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = [for route in routes: {
  parent: api
  name: route.name
  properties: {
    displayName: route.name
    method: route.method
    urlTemplate: route.url
    templateParameters: route.parameters
  }
}]

resource policy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: format('''
<policies>
  <inbound>
    <base />
    <validate-azure-ad-token tenant-id="{0}" header-name="Authorization" failed-validation-httpcode="401">
      <audiences><audience>https://ai.azure.com</audience></audiences>
      <required-claims><claim name="oid" match="all"><value>{1}</value></claim></required-claims>
    </validate-azure-ad-token>
    <set-header name="Ocp-Apim-Subscription-Key" exists-action="delete" />
  </inbound>
  <backend><forward-request timeout="210" buffer-response="false" fail-on-error-status-code="false" /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
''', tenant().tenantId, webAppPrincipalId)
  }
}

resource logger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: gateway
  name: 'application-insights'
  properties: {
    loggerType: 'applicationInsights'
    credentials: { instrumentationKey: instrumentationKey }
    isBuffered: true
  }
}

resource diagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2024-05-01' = {
  parent: api
  name: 'applicationinsights'
  properties: {
    loggerId: logger.id
    alwaysLog: 'allErrors'
    sampling: { samplingType: 'fixed', percentage: 100 }
    httpCorrelationProtocol: 'W3C'
    logClientIp: false
    verbosity: 'error'
    frontend: {
      request: { headers: [], body: { bytes: 0 } }
      response: { headers: [], body: { bytes: 0 } }
    }
    backend: {
      request: { headers: [], body: { bytes: 0 } }
      response: { headers: [], body: { bytes: 0 } }
    }
  }
}

output gatewayId string = gateway.id
