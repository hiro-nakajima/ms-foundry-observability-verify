import json

from agent_framework import Agent, AgentSession
import pytest

from procurement_agent.framework import DeterministicChatClient
from procurement_agent.hosted import PARENT_INSTRUCTIONS, _execute_hosted_components, _with_response_text
from procurement_agent.models import (
    BusinessStatus, OperationStatus, ParseStatus, ProcurementIntake,
    ScenarioResult, TechnicalStatus,
)
from procurement_agent.observability import TelemetryRecorder
from procurement_agent.plan import default_steps
from procurement_agent.session_state import (
    EXECUTION_STATE_KEY, load_execution_state, restore_framework_session,
    save_execution_state,
)
from tests.fixtures.fake_agents import RecordedCatalogAgent, RecordedCodeAgent


class _Tool:
    def __init__(self, name, recorded):
        self.name, self.recorded, self.calls = name, recorded, []

    async def invoke(self, *, arguments, **kwargs):
        from procurement_agent.models import CatalogSearchInput, CodeDeterminationInput
        model = CatalogSearchInput if self.name == 'catalog_search_agent' else CodeDeterminationInput
        payload = model.model_validate_json(arguments['task'])
        self.calls.append(payload)
        return await self.recorded(payload)


def test_missing_memo_guidance_accepts_explicit_none_answer():
    result = ScenarioResult(
        scenario_id='S3', test_case_id='MEMO-NONE',
        technical_status=TechnicalStatus.SUCCESS,
        business_status=BusinessStatus.WAITING_USER,
        status=OperationStatus(
            business_status=BusinessStatus.WAITING_USER,
            parse_status=ParseStatus.SUCCESS,
        ),
        missing_fields=['memo'],
    )

    assert 'メモ（ない場合は「なし」）' in _with_response_text(result).response_text
    assert 'set memo to exactly "なし"' in PARENT_INSTRUCTIONS
    assert ProcurementIntake(
        request={'query': 'ノートPC', 'memo': 'なし'},
        plan={'steps': default_steps()},
    ).request.memo == 'なし'


@pytest.mark.anyio
async def test_incompatible_saved_state_starts_fresh_intake_and_preserves_turn():
    planner = Agent(DeterministicChatClient(lambda *_: ProcurementIntake(
        request={'query': 'ノートPC'}, plan={'steps': default_steps()})))
    catalog = _Tool('catalog_search_agent', RecordedCatalogAgent())
    session = AgentSession()
    session.state[EXECUTION_STATE_KEY] = {
        'schema_version': '2.0', 'architecture_id': 'procurement_application_v2',
        'turn_number': 7, 'test_case_id': 'OLD-WEB',
        'request': {'request_id': 'OLD-1', 'query': 'ノートPC', 'quantity': 1,
                    'applicant_name': '架空 太郎', 'department_name': '開発部（架空部署）',
                    'purpose': '旧用途', 'constraints': {'requested_by': '旧入力'}},
    }
    result = await _execute_hosted_components(
        planner=planner, catalog_tool=catalog,
        code_tool=_Tool('code_determination_agent', RecordedCodeAgent()),
        natural_request='ノートPCを購入したい', session=session,
        test_case_id='WEB-RESUME', telemetry=TelemetryRecorder(), applicant_name='架空 太郎')
    state = load_execution_state(session)
    assert result.business_status == 'WAITING_USER'
    assert result.candidates and state.turn_number == 8
    assert state.request is None
    assert state.warnings == ['session_state_reset_after_schema_change']


@pytest.mark.anyio
async def test_vague_request_lists_grounded_candidates_and_resumes_after_selection(valid_request):
    turn = 0
    def response(messages, options):
        nonlocal turn
        turn += 1
        assert options['response_format']['name'] == 'ProcurementIntake'
        if turn == 1:
            return ProcurementIntake(request={'query': 'ノートPC'}, plan={'steps': default_steps()})
        return ProcurementIntake(request={
            'query': valid_request.query,
            'quantity': valid_request.quantity,
            'department_name': valid_request.department_name,
            'memo': valid_request.memo,
            'constraints': valid_request.constraints.model_dump(mode='json'),
        }, plan={'steps': default_steps()}, selected_product_code='LAPTOP-DEV-14')
    planner = Agent(DeterministicChatClient(response))
    catalog = _Tool('catalog_search_agent', RecordedCatalogAgent())
    codes = _Tool('code_determination_agent', RecordedCodeAgent())
    session = AgentSession()
    args = dict(planner=planner, catalog_tool=catalog, code_tool=codes, telemetry=TelemetryRecorder(),
                test_case_id='WEB-INTAKE', applicant_name='架空 太郎')
    first = await _execute_hosted_components(**args, natural_request='ノートPCを購入したい', session=session)
    assert first.business_status == 'WAITING_USER'
    assert first.status.parse_status == 'SUCCESS'
    assert first.candidates[0].product_code == 'LAPTOP-DEV-14'
    assert first.missing_fields == ['selected_product_code']
    assert catalog.calls[0].quantity is None
    assert not codes.calls and first.draft is None
    assert load_execution_state(session).request is None
    restored = restore_framework_session(session.to_dict())
    second = await _execute_hosted_components(**args, natural_request='商品コード LAPTOP-DEV-14 を選びます。', session=restored)
    assert second.business_status == 'WAITING_USER' and 'quantity' in second.missing_fields
    assert 'selected_product_code' not in second.missing_fields
    assert not codes.calls and second.draft is None
    third = await _execute_hosted_components(**args, natural_request='数量2、所属部署とメモを追加', session=restored)
    assert third.business_status == 'WAITING_USER'
    assert third.missing_fields == ['confirmation']
    assert third.confirmation_preview.account_code == '7210-EQUIPMENT'
    assert '勘定科目' in third.response_text
    assert len(catalog.calls) == 1
    fourth = await _execute_hosted_components(**args, natural_request='確定', session=restored)
    assert fourth.business_status == 'SUCCESS'
    assert fourth.draft.lines[0].product_code == 'LAPTOP-DEV-14'
    assert len(catalog.calls) == 1
    assert len(codes.calls) == 1
    assert load_execution_state(restored).turn_number == 4
    assert ScenarioResult.model_validate_json(fourth.model_dump_json()) == fourth
    fifth = await _execute_hosted_components(**args, natural_request='確定', session=restored)
    reset = load_execution_state(restored)
    assert fifth.scenario_id == 'CHAT'
    assert fifth.interaction_type == 'general'
    assert '購入したい商品' in fifth.response_text
    assert reset.plan is None and reset.intake is None and reset.catalog_result is None
    assert reset.turn_number == 5
    assert len(catalog.calls) == 1 and len(codes.calls) == 1


@pytest.mark.anyio
async def test_exact_business_card_match_advances_through_each_intake_step():
    turns = [
        {'query': '名刺'},
        {'query': '名刺', 'quantity': 10},
        {'query': '名刺', 'quantity': 10, 'department_name': '営業部'},
        {'query': '名刺', 'quantity': 10, 'department_name': '営業部', 'memo': 'なし'},
    ]
    turn = 0

    def response(*_):
        nonlocal turn
        request = turns[turn]
        turn += 1
        return ProcurementIntake(request=request, plan={'steps': default_steps()})

    planner = Agent(DeterministicChatClient(response))
    catalog = _Tool(
        'catalog_search_agent', RecordedCatalogAgent('catalog-business-card.json'),
    )
    codes = _Tool(
        'code_determination_agent', RecordedCodeAgent('code-business-card.json'),
    )
    session = AgentSession()
    args = dict(
        planner=planner, catalog_tool=catalog, code_tool=codes, session=session,
        test_case_id='WEB-BUSINESS-CARD', telemetry=TelemetryRecorder(),
        applicant_name='架空 太郎',
    )

    product = await _execute_hosted_components(
        **args, natural_request='名刺を購入したい',
    )
    state = load_execution_state(session)
    assert product.missing_fields == ['quantity']
    assert product.status.reason_code == 'SINGLE_EXACT_CATALOG_MATCH'
    assert '数量' in product.response_text
    assert state.selected_product_code == 'BUSINESS-CARD-01'
    assert product.candidates == []

    quantity = await _execute_hosted_components(**args, natural_request='10個')
    assert quantity.missing_fields == ['department_name']
    assert load_execution_state(session).intake.quantity == 10

    department = await _execute_hosted_components(**args, natural_request='営業部')
    assert department.missing_fields == ['memo']
    assert load_execution_state(session).intake.department_name == '営業部'

    memo = await _execute_hosted_components(**args, natural_request='なし')
    assert memo.missing_fields == ['confirmation']
    assert load_execution_state(session).intake.memo == 'なし'
    assert memo.confirmation_preview.model_dump(mode='json') == {
        'applicant_authenticated': True,
        'applicant_name': '架空 太郎',
        'product_code': 'BUSINESS-CARD-01',
        'product_name': '名刺',
        'category': 'printing',
        'specifications': {'size': '91x55mm', 'print': '両面カラー'},
        'unit_price': '100.0',
        'currency': 'JPY',
        'quantity': 10,
        'subtotal': '1000.0',
        'department_code': 'DPT-SALES',
        'department_name': '営業部（架空部署）',
        'account_code': '7310-SUPPLIES',
        'account_name': '周辺機器消耗品（架空科目）',
        'memo': 'なし',
    }
    for expected in (
        '名刺（BUSINESS-CARD-01）', '単価: 100円', '数量: 10', '小計: 1,000円',
        '営業部（架空部署）（DPT-SALES）', '7310-SUPPLIES', 'メモ: なし',
        '申請者: 架空 太郎（EasyAuth認証済み）',
    ):
        assert expected in memo.response_text

    confirmed = await _execute_hosted_components(**args, natural_request='確定')
    assert confirmed.business_status == 'SUCCESS'
    assert confirmed.draft.lines[0].product_code == 'BUSINESS-CARD-01'
    assert confirmed.draft.lines[0].quantity == 10
    assert confirmed.draft.department_code == 'DPT-SALES'
    assert confirmed.draft.memo == 'なし'
    assert len(catalog.calls) == 1
    assert len(codes.calls) == 1


@pytest.mark.anyio
async def test_catalog_not_found_does_not_save_later_intake_fields_or_requery():
    turn = 0

    def response(*_):
        nonlocal turn
        turn += 1
        request = {'query': '名刺'}
        if turn > 1:
            request['quantity'] = 10
        return ProcurementIntake(request=request, plan={'steps': default_steps()})

    catalog = _Tool(
        'catalog_search_agent', RecordedCatalogAgent('catalog-not-found.json'),
    )
    session = AgentSession()
    args = dict(
        planner=Agent(DeterministicChatClient(response)), catalog_tool=catalog,
        code_tool=_Tool('code_determination_agent', RecordedCodeAgent()),
        session=session, test_case_id='WEB-CATALOG-NOT-FOUND',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎',
    )

    first = await _execute_hosted_components(
        **args, natural_request='名刺を購入したい',
    )
    assert first.missing_fields == ['selected_product_code']
    assert '確認できませんでした' in first.response_text
    assert len(catalog.calls) == 2

    second = await _execute_hosted_components(**args, natural_request='10個')
    state = load_execution_state(session)
    assert second.missing_fields == ['selected_product_code']
    assert state.intake.quantity is None
    assert len(catalog.calls) == 2


@pytest.mark.anyio
async def test_explicit_product_retry_clears_legacy_fields_after_catalog_failure():
    planner_turn = 0

    def response(*_):
        nonlocal planner_turn
        planner_turn += 1
        request = {'query': '名刺'}
        if planner_turn > 1:
            request.update(quantity=10, department_name='営業部', memo='なし')
        return ProcurementIntake(request=request, plan={'steps': default_steps()})

    catalog_call = 0

    async def recorded_catalog(payload):
        nonlocal catalog_call
        catalog_call += 1
        fixture = 'catalog-not-found.json' if catalog_call <= 2 else 'catalog-business-card.json'
        return await RecordedCatalogAgent(fixture)(payload)

    catalog = _Tool('catalog_search_agent', recorded_catalog)
    session = AgentSession()
    args = dict(
        planner=Agent(DeterministicChatClient(response)), catalog_tool=catalog,
        code_tool=_Tool('code_determination_agent', RecordedCodeAgent()),
        session=session, test_case_id='WEB-CATALOG-RETRY',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎',
    )
    failed = await _execute_hosted_components(
        **args, natural_request='名刺を購入したい',
    )
    assert failed.missing_fields == ['selected_product_code']

    legacy = load_execution_state(session)
    legacy.intake = legacy.intake.model_copy(update={
        'quantity': 10, 'department_name': '営業部', 'memo': 'なし',
    })
    save_execution_state(session, legacy)

    retried = await _execute_hosted_components(
        **args, natural_request='名刺を購入したい',
    )
    state = load_execution_state(session)
    assert retried.missing_fields == ['quantity']
    assert state.selected_product_code == 'BUSINESS-CARD-01'
    assert state.intake.quantity is None
    assert state.intake.department_name is None
    assert state.intake.memo is None
    assert len(catalog.calls) == 3


@pytest.mark.anyio
async def test_missing_query_is_normal_clarification_without_tool_call():
    planner = Agent(DeterministicChatClient(lambda *_: ProcurementIntake(request={}, plan={'steps': default_steps()})))
    catalog = _Tool('catalog_search_agent', RecordedCatalogAgent())
    codes = _Tool('code_determination_agent', RecordedCodeAgent())
    result = await _execute_hosted_components(planner=planner, catalog_tool=catalog, code_tool=codes,
        natural_request='購入を相談したい', session=AgentSession(), test_case_id='WEB-EMPTY',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎')
    assert result.business_status == 'WAITING_USER' and 'query' in result.missing_fields
    assert result.status.mcp_status == 'NOT_RUN'
    assert not catalog.calls and not codes.calls


@pytest.mark.anyio
async def test_unseen_selection_is_rejected_without_tool_call():
    planner = Agent(DeterministicChatClient(lambda *_: ProcurementIntake(
        request={'query': 'ノートPC'}, plan={'steps': default_steps()}, selected_product_code='INVENTED')))
    catalog = _Tool('catalog_search_agent', RecordedCatalogAgent())
    codes = _Tool('code_determination_agent', RecordedCodeAgent())
    result = await _execute_hosted_components(planner=planner, catalog_tool=catalog, code_tool=codes,
        natural_request='購入する商品を選ぶ', session=AgentSession(), test_case_id='WEB-UNKNOWN', telemetry=TelemetryRecorder())
    assert result.business_status == 'INVALID_INPUT'
    assert not catalog.calls and not codes.calls


@pytest.mark.anyio
async def test_general_and_identity_turns_do_not_enter_procurement_plan():
    calls = 0
    def planner(*_):
        nonlocal calls
        calls += 1
        raise AssertionError('non-procurement intent must not call the planner')
    catalog = _Tool('catalog_search_agent', RecordedCatalogAgent())
    codes = _Tool('code_determination_agent', RecordedCodeAgent())
    session = AgentSession()
    args = dict(planner=Agent(DeterministicChatClient(planner)), catalog_tool=catalog,
                code_tool=codes, session=session, telemetry=TelemetryRecorder(),
                test_case_id='CHAT-ROUTING', applicant_name='架空 太郎')
    greeting = await _execute_hosted_components(**args, natural_request='こんにちは')
    identity = await _execute_hosted_components(**args, natural_request='私は誰？')
    state = load_execution_state(session)
    assert greeting.scenario_id == 'CHAT' and greeting.interaction_type == 'general'
    assert identity.scenario_id == 'IDENTITY' and identity.interaction_type == 'identity'
    assert '架空 太郎' in identity.response_text and 'EasyAuth' in identity.response_text
    assert state.plan is None and state.turn_number == 2
    assert state.last_machine_response['outer_business_status'] == 'SUCCESS'
    assert state.last_machine_response['mcp_status'] == 'NOT_RUN'
    response_spans = [span for span in args['telemetry'].finished_spans()
                      if span.name == 'response.generate']
    assert [span.attributes['app.turn.number'] for span in response_spans] == [1, 2]
    assert all(span.attributes['mcp.status'] == 'NOT_RUN' for span in response_spans)
    assert calls == 0 and not catalog.calls and not codes.calls


@pytest.mark.anyio
@pytest.mark.parametrize('message', [
    'ノートPCが欲しい', 'モニターを注文したい', 'ノートPCを2台',
])
async def test_ordinary_purchase_phrasing_enters_procurement(message):
    planner = Agent(DeterministicChatClient(lambda *_: ProcurementIntake(
        request={'query': 'ノートPC'}, plan={'steps': default_steps()},
    )))
    catalog = _Tool('catalog_search_agent', RecordedCatalogAgent())
    result = await _execute_hosted_components(
        planner=planner, catalog_tool=catalog,
        code_tool=_Tool('code_determination_agent', RecordedCodeAgent()),
        natural_request=message, session=AgentSession(),
        test_case_id='CHAT-PURCHASE-INTENT', telemetry=TelemetryRecorder(),
        applicant_name='架空 太郎',
    )
    assert result.interaction_type == 'procurement'
    assert catalog.calls


@pytest.mark.anyio
async def test_code_clarification_does_not_request_product_reselection(valid_request):
    calls = 0
    def plan(*_):
        nonlocal calls
        calls += 1
        request = {'query': valid_request.query}
        if calls > 1:
            request.update(quantity=valid_request.quantity,
                           department_name=('存在しない部（架空部署）' if calls == 2 else valid_request.department_name),
                           memo=valid_request.memo, constraints=valid_request.constraints.model_dump(mode='json'))
        return ProcurementIntake(request=request, plan={'steps': default_steps()})
    planner = Agent(DeterministicChatClient(plan))
    code_calls = 0
    async def unknown_department(payload):
        nonlocal code_calls
        code_calls += 1
        if code_calls == 1:
            assert load_execution_state(session).intake.department_name is None
            result = await RecordedCodeAgent('code-not-found.json')(payload)
            result.status = result.status.model_copy(update={
                'business_status': BusinessStatus.WAITING_USER,
                'reason_code': 'DEPARTMENT_NOT_FOUND',
            })
            return result
        return await RecordedCodeAgent()(payload)
    catalog = _Tool('catalog_search_agent', RecordedCatalogAgent())
    codes = _Tool('code_determination_agent', unknown_department)
    session = AgentSession()
    first = await _execute_hosted_components(planner=planner, catalog_tool=catalog, code_tool=codes,
        natural_request='架空の未登録部署から申請', session=session, test_case_id='WEB-DEPARTMENT',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎')
    assert first.business_status == 'WAITING_USER'
    await _execute_hosted_components(planner=planner, catalog_tool=catalog, code_tool=codes,
        natural_request='商品コード LAPTOP-DEV-14 を選びます。', session=session, test_case_id='WEB-DEPARTMENT',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎')
    rejected = await _execute_hosted_components(planner=planner, catalog_tool=catalog, code_tool=codes,
        natural_request='数量、部署、メモを入力', session=session, test_case_id='WEB-DEPARTMENT',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎')
    state = load_execution_state(session)
    assert rejected.business_status == 'WAITING_USER' and rejected.draft is None
    assert rejected.status.reason_code == 'DEPARTMENT_NOT_FOUND'
    assert rejected.missing_fields == ['department_name']
    assert rejected.candidates == [] and state.selected_product_code == 'LAPTOP-DEV-14'
    assert state.intake.department_name is None
    assert '登録済みの所属部署' in rejected.response_text
    assert len(catalog.calls) == 1 and len(codes.calls) == 1
    ready = await _execute_hosted_components(planner=planner, catalog_tool=catalog, code_tool=codes,
        natural_request='所属部署は開発部（架空部署）', session=session, test_case_id='WEB-DEPARTMENT',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎')
    assert ready.missing_fields == ['confirmation']
    assert load_execution_state(session).intake.query == valid_request.query
    assert len(catalog.calls) == 1 and len(codes.calls) == 2
    result = await _execute_hosted_components(planner=planner, catalog_tool=catalog, code_tool=codes,
        natural_request='確定', session=session, test_case_id='WEB-DEPARTMENT',
        telemetry=TelemetryRecorder(), applicant_name='架空 太郎')
    assert result.business_status == 'SUCCESS' and result.draft is not None
    assert result.draft.department_name == valid_request.department_name
    assert len(catalog.calls) == 1 and len(codes.calls) == 2
