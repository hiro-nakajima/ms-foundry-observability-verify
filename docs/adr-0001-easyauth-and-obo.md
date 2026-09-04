# ADR-0001: EasyAuth claims for the procurement path; OBO is a separate validation path

## Decision

The App Service WebUI uses Microsoft Entra EasyAuth for browser authentication.
It reads `tid`, `oid`, and the display-name `name` claim from
`X-MS-CLIENT-PRINCIPAL`. `tid` and `oid` derive a stable SHA-256 pseudonymous
`user.id`, which is placed on the App Service root span and W3C baggage. The
validated display name is sent only as authenticated request context to the
Hosted parent and stored in Framework `AgentSession.state` as the applicant.
Raw claims, names, email addresses, tokens, and the complete `traceparent`
value are not persisted as custom attributes or baggage.

App Service invokes the Foundry Hosted parent using its system-assigned managed
identity. The Hosted parent and Toolbox/Search runtime retain their separate
identities and least-privilege roles. OBO is not used to obtain the procurement
applicant name.

The APIM gateway requested on 2026-09-03 validates the App Service managed
identity's tenant, audience and object ID, then forwards its Bearer token to the
fixed Foundry backend. It does not exchange that token for a user token or an
APIM identity token. The reference application's refresh-token/OBO code remains
as user-provided reference source, but is excluded from the deployment ZIP.

## Rationale

EasyAuth already supplies the signed-in user's display-name claim at the trusted
App Service boundary. OBO is not implicit: it would require a delegated user
assertion, confidential-client exchange, Graph `User.Read`, and `/me`. None of
those are needed merely to populate an applicant display name. Search
queries are authorized by the Toolbox runtime identity, and no downstream
Microsoft Graph or user-delegated API is in scope. EasyAuth plus managed
identity keeps browser authentication, service authorization, and trace
correlation separate.

OBO remains useful as a separate interoperability validation when a downstream
API must enforce the authenticated user's delegated permissions. A later
Functions + Entra confidential-client path may exchange the EasyAuth user token
and call Microsoft Graph `/me`, following the reference environment. That path
must have its own permissions and validation and must not become a dependency of
the procurement applicant-name flow.

## Verification boundary

On 2026-09-03, the actual EasyAuth authorization request used
`response_type=code id_token`, while the dedicated registration had ID-token
issuance disabled. The callback URI matched exactly and the configured secret
was present and matched the deployment credential (values were not emitted).
Enabled only `web.implicitGrantSettings.enableIdTokenIssuance`; implicit access
token issuance remains disabled and no delegated API permissions were added.
The user subsequently confirmed successful sign-in and the rendered chat UI.
The original black callback page did not expose an error code, so no particular
AADSTS code or exclusive root cause is claimed. Authenticated chat/trace
propagation is a separate verification from successful sign-in.

The WebUI has Local cookie/claim/CSRF-boundary tests and a real HTTP fixture that
observes SDK/HTTPX automatic traceparent and pseudonymous baggage injection.
The deployed HTTP transport also records only boolean observations of the
actual outgoing traceparent/span match and allowlisted user.id baggage match.
It does not manually inject headers or duplicate raw traceparent attributes.
Browser success Trace `c876a5a2b4997bb2f44aaffb76829f7b` measured the
outgoing `traceparent`/span match and the full observed Web -> Hosted -> Prompt
children -> Toolboxes -> merge/response path under one Trace ID. The outgoing
`user.id` baggage matched at the Web transport, but no downstream managed span
recorded `user.id`; this is reported as `NOT_PROPAGATED` without assigning the
loss to a specific unobservable hop. APIM/Search internal spans are
`NOT_RECORDED_BY_PLATFORM`.
