#!/usr/bin/env python3
"""Measure genuine progress and a four-turn synthetic intake through Hosted.

Direct Foundry only: this is not proof of App Service/EasyAuth/APIM streaming.
"""
from datetime import datetime, timezone
import json
import time

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from deploy_foundation import STATE, save
from deploy_foundry import ENDPOINT
from procurement_agent.models import ScenarioResult
from procurement_agent.progress import STEPS, STATES


def main():
    case = 'CHAT-DIRECT-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    evidence = {'case': case, 'path': 'direct-foundry-not-webapp', 'turns': []}
    with AzureCliCredential() as credential, AIProjectClient(endpoint=ENDPOINT, credential=credential, allow_preview=True) as project:
        version = json.loads((STATE / 'foundry-deployment.json').read_text())['procurement-parent-agent']['version']
        active = project.agents.get_version(agent_name='procurement-parent-agent', agent_version=version)
        if active.status != 'active':
            raise RuntimeError('Expected Hosted version is not active')
        evidence['expected_agent_version'] = version
        with project.get_openai_client(agent_name='procurement-parent-agent', max_retries=0, timeout=240) as client:
            conv = client.conversations.create(metadata={'test.case.id': case, 'synthetic': 'true'})
            evidence['conversation_id'] = conv.id
            save(STATE / f'{case}.json', evidence)
            message = 'ノートPCを購入したい'
            selected_code = None
            for turn in (1, 2, 3, 4):
                started, pending, milestones, final = time.monotonic(), '', [], None
                with client.responses.create(conversation=conv.id, input=message, stream=True,
                    metadata={'test.case.id': case, 'app.turn.number': str(turn),
                              'app.authenticated.display_name': '架空 太郎'}) as stream:
                    for event in stream:
                        if event.type == 'response.output_text.delta':
                            pending += event.delta
                            while '\n' in pending:
                                line, pending = pending.split('\n', 1)
                                try:
                                    value = json.loads(line.lstrip(','))
                                    if value.get('step') in STEPS and value.get('state') in STATES:
                                        milestone = {'step': value['step'], 'state': value['state'], 'seconds': round(time.monotonic() - started, 3)}
                                        milestones.append(milestone)
                                        print(json.dumps({'turn': turn, 'progress': milestone}), flush=True)
                                except (ValueError, AttributeError):
                                    pass
                        elif event.type == 'response.completed':
                            final = event.response
                        elif event.type in {'response.failed', 'response.incomplete', 'error'}:
                            raise RuntimeError('Hosted stream failed; body withheld')
                if final is None:
                    raise RuntimeError('No completed response')
                result = ScenarioResult.model_validate_json(final.output_text)
                entry = {'turn': turn, 'seconds': round(time.monotonic() - started, 3), 'milestones': milestones,
                         'response_id': final.id, 'technical': result.technical_status.value, 'business': result.business_status.value,
                         'status': result.status.model_dump(mode='json') if result.status else None,
                         'candidate_codes': [c.product_code for c in result.candidates], 'missing_fields': result.missing_fields,
                         'correlation': result.trace.get('correlation'), 'draft_present': result.draft is not None}
                evidence['turns'].append(entry)
                save(STATE / f'{case}.json', evidence)
                print(json.dumps({'case': case, **entry}, ensure_ascii=False), flush=True)
                if turn == 1:
                    if result.business_status != 'WAITING_USER' or not result.candidates:
                        raise RuntimeError('First turn did not provide candidates')
                    selected_code = result.candidates[0].product_code
                    message = f'商品コード {selected_code} を選びます'
                elif turn == 2:
                    if result.business_status != 'WAITING_USER':
                        raise RuntimeError('Product selection did not continue intake')
                    message = '数量は2台、所属部署は開発部（架空部署）、メモは開発用です'
                elif turn == 3:
                    if result.business_status != 'WAITING_USER' or 'confirmation' not in result.missing_fields:
                        raise RuntimeError('Completed intake did not request confirmation')
                    message = '確定'
                elif result.business_status != 'SUCCESS' or result.draft is None:
                    raise RuntimeError('Confirmed request did not complete successfully')
                if not milestones or milestones[0]['seconds'] >= entry['seconds']:
                    raise RuntimeError('Progress before completion was not measured')
            hashes = {(t.get('correlation') or {}).get('framework_session_id_hash') for t in evidence['turns']}
            if None in hashes or len(hashes) != 1:
                raise RuntimeError('Framework session correlation was not preserved')
            for entry in evidence['turns'][1:3]:
                if any(item['step'] == 'catalog' and item['state'] == 'started' for item in entry['milestones']):
                    raise RuntimeError('Catalog was unexpectedly restarted during saved intake')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'http_status': getattr(exc, 'status_code', None), 'body': 'withheld'}))
        raise SystemExit(1)
