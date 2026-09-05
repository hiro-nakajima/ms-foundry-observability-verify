import importlib
import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def deployment(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'scripts'))
    return importlib.import_module('deploy_blob_indexers')


def test_blob_definitions_use_existing_indexes_and_keyless_auth(deployment):
    for container, index in zip(deployment.CONTAINERS, deployment.INDEXES):
        source, indexer = deployment.definitions(container, index)
        assert source['type'] == 'azureblob'
        assert source['credentials'] == {'connectionString': f'ResourceId={deployment.STORAGE_ID};'}
        assert source['container'] == {'name': container}
        assert indexer['targetIndexName'] == index
        assert indexer['parameters']['configuration'] == {'parsingMode': 'jsonArray'}
        assert indexer['parameters']['maxFailedItems'] == 0
        assert indexer['parameters']['maxFailedItemsPerBatch'] == 0
        assert indexer['fieldMappings'] == [{'sourceFieldName': 'document_id', 'targetFieldName': 'document_id'}]
        assert 'schedule' not in indexer


def test_readback_comparison_requires_all_documents_and_values(deployment):
    assert deployment._contains({'a': [{'id': '1', 'value': 3, 'extra': None}]}, {'a': [{'id': '1', 'value': 3}]})
    assert not deployment._contains({'a': []}, {'a': [{'id': '1'}]})
    assert not deployment._contains({'a': [{'id': '1', 'value': 4}]}, {'a': [{'id': '1', 'value': 3}]})


def test_preflight_rejects_existing_schema_without_writes(deployment):
    requests = []
    def handle(request):
        requests.append(request.method)
        return httpx.Response(200, json={'fields': []})
    with httpx.Client(base_url='https://fixture', transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RuntimeError, match='schema differs'):
            deployment._preflight(client)
    assert requests == ['GET']


@pytest.mark.parametrize('processed,ended,valid', [(11, '2026-09-03T10:01:00Z', True),
                                                 (10, '2026-09-03T10:01:00Z', False),
                                                 (11, '2026-09-03T09:00:00Z', False)])
def test_matching_search_data_is_not_proof_of_current_indexer_run(deployment, monkeypatch, tmp_path, processed, ended, valid):
    catalog, codes, manifest = deployment.build_documents()
    monkeypatch.setattr(deployment, 'STATE', tmp_path)
    deployment.save(tmp_path / 'blob-ingestion-request.json', {
        'requested_at': '2026-09-03T10:00:00+00:00', 'storage': deployment.STORAGE_ID, 'manifest': manifest})
    def handle(request):
        if request.url.path.endswith('/status'):
            run = {'status': 'success', 'itemsProcessed': processed, 'itemsFailed': 0, 'endTime': ended}
            return httpx.Response(200, json={'lastResult': run, 'executionHistory': [run]})
        docs = catalog if 'catalog' in request.url.path else codes
        return httpx.Response(200, json={'value': docs, '@odata.count': len(docs)})
    with httpx.Client(base_url='https://fixture', transport=httpx.MockTransport(handle)) as client:
        if valid:
            deployment.verify(client)
        else:
            with pytest.raises(RuntimeError, match='incomplete'):
                deployment.verify(client)
    evidence = json.loads((tmp_path / 'blob-indexer-verification.json').read_text())
    assert all(x['repository_projection_matches'] for x in evidence['indexes'])
