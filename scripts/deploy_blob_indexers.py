#!/usr/bin/env python3
"""Approved synthetic Blob ingestion into the existing Serverless indexes.

No index replacement, deletion, shared keys, schedules, or Foundry changes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import sys

import httpx
from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from deploy_foundation import ROOT, STATE, SUB, RG, az, save
from deploy_search import NAME, SCOPE, INDEXES
from prepare_search_documents import build_documents

API = '2026-08-01-preview'
STORAGE = 'stprocurementobsnkjm'
STORAGE_ID = f'/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/{STORAGE}'
CONTAINERS = ('procurement-catalog', 'procurement-code-master')
PARAMS = STATE / 'search-blob.parameters.json'
SOURCE_ETAGS = STATE / 'blob-source-etags.json'


def definitions(container, index):
    source = {
        'name': container + '-blob-source', 'type': 'azureblob',
        'description': 'Repository synthetic JSON; managed identity; no account keys',
        'credentials': {'connectionString': f'ResourceId={STORAGE_ID};'},
        'container': {'name': container},
    }
    indexer = {
        'name': container + '-blob-indexer', 'dataSourceName': source['name'],
        'targetIndexName': index,
        'parameters': {'maxFailedItems': 0, 'maxFailedItemsPerBatch': 0,
                       'configuration': {'parsingMode': 'jsonArray'}},
        'fieldMappings': [{'sourceFieldName': 'document_id', 'targetFieldName': 'document_id'}],
    }
    return source, indexer


def infrastructure(apply=False):
    search = az('resource', 'show', '--ids', SCOPE, '--api-version', '2026-03-01-preview')
    principal = (search.get('identity') or {}).get('principalId')
    if not principal:
        raise RuntimeError('Search system MI must exist before Storage deployment')
    caller = az('ad', 'signed-in-user', 'show')['id']
    save(PARAMS, {'parameters': {k: {'value': v} for k, v in {
        'searchPrincipalId': principal, 'ingestorPrincipalId': caller,
    }.items()}})
    args = ['--resource-group', RG, '--name', 'procurement-search-blob',
            '--template-file', str(ROOT / 'infra/search-blob.bicep'),
            '--parameters', '@' + str(PARAMS), '--mode', 'Incremental']
    result = az('deployment', 'group', 'what-if', *args, '--no-pretty-print')
    save(STATE / 'search-blob-what-if.json', result)
    changes = result.get('changes', [])
    if result.get('status') != 'Succeeded' or any(
        x['changeType'] not in ('Create', 'NoChange', 'Ignore') or
        (x['changeType'] == 'Create' and not x['resourceId'].lower().startswith(STORAGE_ID.lower()))
        for x in changes
    ):
        raise RuntimeError('What-if is not create-only within dedicated Storage; inspect without applying')
    print(json.dumps({'what_if': [{'id': x['resourceId'], 'change': x['changeType']}
                                for x in changes if x['changeType'] != 'Ignore']}), flush=True)
    if apply:
        result = az('deployment', 'group', 'create', *args)
        status = result['properties']['provisioningState']
        print('Storage deployment: ' + status, flush=True)
        if status != 'Succeeded':
            raise RuntimeError('Deployment did not succeed')


def request(client, method, path, **kwargs):
    result = client.request(method, path, params={'api-version': API}, **kwargs)
    if not result.is_success:
        # Never echo data source credentials or provider error bodies.
        raise RuntimeError(f'Search {method} {path}: HTTP {result.status_code}; body withheld')
    return result


def _contains(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(_contains(actual.get(k), v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _contains(a, e) for a, e in zip(actual, expected))
    return actual == expected


def _preflight(client):
    known_etags = json.loads(SOURCE_ETAGS.read_text()) if SOURCE_ETAGS.exists() else {}
    for container, index in zip(CONTAINERS, INDEXES):
        schema = request(client, 'GET', f'/indexes/{index}').json()
        expected = json.loads((ROOT / 'infra/search/indexes' / f'{index}.json').read_text())
        actual_fields = {field['name']: field for field in schema['fields']}
        expected_fields = {field['name']: field for field in expected['fields']}
        if actual_fields.keys() != expected_fields.keys() or not _contains(actual_fields, expected_fields):
            raise RuntimeError('Existing index schema differs; no schema changes allowed')
        for kind, value in zip(('datasources', 'indexers'), definitions(container, index)):
            response = client.get(f'/{kind}/{value["name"]}', params={'api-version': API})
            if response.status_code == 404:
                continue
            if response.status_code != 200:
                raise RuntimeError(f'{kind} preflight: HTTP {response.status_code}')
            actual = response.json()
            # Azure can mask credentials on GET. Verify everything else; never replace.
            expected_value = {k: v for k, v in value.items() if k != 'credentials'}
            if not _contains(actual, expected_value) or (kind == 'indexers' and actual.get('schedule')):
                raise RuntimeError(f'Existing {kind} differs; refusing overwrite')
            if kind == 'datasources' and (
                actual.get('identity') or actual['container'].get('query') or
                (actual.get('credentials') != value['credentials'] and
                 known_etags.get(value['name']) != actual.get('@odata.etag'))
            ):
                raise RuntimeError('Data source credentials are masked or changed without a matching deployment ETag')


def ingest(client, credential):
    _preflight(client)
    catalog, codes, manifest = build_documents()
    save(STATE / 'blob-ingestion-request.json', {'requested_at': datetime.now(timezone.utc).isoformat(),
                                               'storage': STORAGE_ID, 'manifest': manifest})
    with BlobServiceClient(f'https://{STORAGE}.blob.core.windows.net', credential=credential) as blobs:
        for container, documents in zip(CONTAINERS, (catalog, codes)):
            payload = json.dumps(documents, ensure_ascii=False, sort_keys=True).encode()
            blob = blobs.get_blob_client(container, 'documents.json')
            # This dedicated blob is generated only from repository synthetic data.
            blob.upload_blob(payload, overwrite=True, content_settings=ContentSettings(content_type='application/json'),
                             metadata={'source_version': manifest['source_version'],
                                       'sha256': hashlib.sha256(payload).hexdigest()})
            if blob.download_blob().readall() != payload:
                raise RuntimeError('Blob read-back mismatch')
            print(f'Blob {container}: {len(documents)} synthetic documents, {len(payload)} bytes; read-back matched', flush=True)
    for container, index in zip(CONTAINERS, INDEXES):
        source, indexer = definitions(container, index)
        created_indexer = False
        for kind, value in (('datasources', source), ('indexers', indexer)):
            path = f'/{kind}/{value["name"]}'
            current = client.get(path, params={'api-version': API})
            if current.status_code == 404:
                request(client, 'PUT', path, json=value, headers={'If-None-Match': '*'})
                if kind == 'datasources':
                    observed = request(client, 'GET', path).json()
                    etags = json.loads(SOURCE_ETAGS.read_text()) if SOURCE_ETAGS.exists() else {}
                    etags[value['name']] = observed['@odata.etag']
                    save(SOURCE_ETAGS, etags)
                created_indexer = kind == 'indexers'
                print('Created ' + path, flush=True)
            elif current.status_code != 200:
                raise RuntimeError(f'Pre-create read: HTTP {current.status_code}')
        if not created_indexer:  # New indexers run automatically; no duplicate concurrent run.
            request(client, 'POST', f'/indexers/{indexer["name"]}/run')


def verify(client):
    catalog, codes, manifest = build_documents()
    submitted = json.loads((STATE / 'blob-ingestion-request.json').read_text())
    if submitted['manifest'] != manifest or submitted['storage'] != STORAGE_ID:
        raise RuntimeError('Submission does not match the current source projection')
    requested_at = datetime.fromisoformat(submitted['requested_at'])
    results = []
    for container, index, documents in zip(CONTAINERS, INDEXES, (catalog, codes)):
        name = definitions(container, index)[1]['name']
        status = request(client, 'GET', f'/indexers/{name}/status').json()
        latest = status.get('lastResult') or {}
        history = status.get('executionHistory') or []
        execution = next((x for x in history if x.get('status') == 'success' and
                          x.get('itemsProcessed', 0) >= len(documents) and not x.get('itemsFailed') and
                          x.get('endTime') and datetime.fromisoformat(x['endTime'].replace('Z', '+00:00')) >= requested_at), {})
        response = request(client, 'POST', f'/indexes/{index}/docs/search',
                           json={'search': '*', 'top': 100, 'count': True}).json()
        actual = {x['document_id']: x for x in response['value']}
        match = len(actual) == response['@odata.count'] == len(documents) and all(
            _contains(actual.get(x['document_id']), x) for x in documents)
        results.append({'index': index, 'indexer': name, 'status': latest.get('status'),
                        'items_processed': latest.get('itemsProcessed'), 'items_failed': latest.get('itemsFailed'),
                        'error_count': len(latest.get('errors') or []),
                        'warning_count': len(latest.get('warnings') or []),
                        'full_ingestion_succeeded_at': execution.get('endTime'),
                        'document_count': response['@odata.count'], 'repository_projection_matches': match})
    evidence = {'checked_at': datetime.now(timezone.utc).isoformat(), 'storage': STORAGE_ID,
                'search': SCOPE, 'manifest': manifest, 'indexes': results}
    save(STATE / 'blob-indexer-verification.json', evidence)
    print(json.dumps(evidence), flush=True)
    if not all(x['status'] == 'success' and x['full_ingestion_succeeded_at'] and
               not x['error_count'] and not x['items_failed'] and x['repository_projection_matches'] for x in results):
        raise RuntimeError('Indexer verification incomplete; do not report PASS')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan', 'apply', 'ingest', 'verify'))
    args = parser.parse_args()
    if az('account', 'show')['id'] != SUB:
        raise RuntimeError('Wrong subscription; no writes')
    if args.action in ('plan', 'apply'):
        infrastructure(args.action == 'apply')
        return
    with AzureCliCredential() as credential, httpx.Client(base_url=f'https://{NAME}.search.windows.net', timeout=60) as client:
        client.headers['Authorization'] = 'Bearer ' + credential.get_token('https://search.azure.com/.default').token
        if args.action == 'ingest':
            ingest(client, credential)
        else:
            verify(client)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
