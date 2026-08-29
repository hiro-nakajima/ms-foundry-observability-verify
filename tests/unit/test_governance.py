from __future__ import annotations

from pathlib import Path

import pytest

from procurement_agent.governance import GovernanceAdapter, GovernanceDenied
from procurement_agent.models import (
    AgentRole,
    BusinessStatus,
    GovernanceMode,
    GovernanceOutcome,
    PlanStatus,
    ToolResponse,
)


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "src" / "procurement_agent" / "policies" / "policy.yaml"


def _pre_tool(adapter: GovernanceAdapter, role: AgentRole, tool: str):
    return adapter.pre_tool(
        agent_role=role,
        tool_name=tool,
        plan_id="plan-1",
        step_id="S03",
        plan_status=PlanStatus.RUNNING,
        duplicate_step=False,
        missing_required_information=False,
        tool_call_count=1,
        agent_tool_call_count=0,
    )


def test_policy_loads_with_all_four_stages() -> None:
    adapter = GovernanceAdapter(POLICY)
    assert adapter.policy_version == "1.0.0"
    assert {rule.stage for rule in adapter.policy.rules} == {
        "pre_input",
        "pre_tool",
        "post_tool",
        "pre_output",
    }


def test_shadow_records_would_deny_but_does_not_block() -> None:
    adapter = GovernanceAdapter(POLICY, mode=GovernanceMode.SHADOW)
    decision = _pre_tool(adapter, AgentRole.COORDINATOR, "search_catalog")
    assert decision.outcome == GovernanceOutcome.WOULD_DENY
    assert decision.rule_id == "coordinator-direct-data-tool"


def test_enforce_blocks_role_tool_violation() -> None:
    adapter = GovernanceAdapter(POLICY, mode=GovernanceMode.ENFORCE)
    with pytest.raises(GovernanceDenied) as exc:
        _pre_tool(adapter, AgentRole.DRAFTING_SPECIALIST, "search_catalog")
    assert exc.value.decision.outcome == GovernanceOutcome.DENY


def test_allowlisted_single_agent_tool_is_allowed() -> None:
    decision = _pre_tool(
        GovernanceAdapter(POLICY, mode=GovernanceMode.ENFORCE),
        AgentRole.PROCUREMENT_ASSISTANT,
        "calculate_request",
    )
    assert decision.outcome == GovernanceOutcome.ALLOW


def test_successful_tool_without_evidence_is_would_deny_in_shadow() -> None:
    response = ToolResponse(
        call_id="tool-1",
        business_status=BusinessStatus.SUCCESS,
        data_version="2026-08-28.1",
        result={"value": 1},
    )
    decision = GovernanceAdapter(POLICY).post_tool(
        agent_role=AgentRole.PROCUREMENT_ASSISTANT,
        tool_name="get_catalog_item",
        response=response,
        plan_id="plan-1",
        step_id="S04",
    )
    assert decision.outcome == GovernanceOutcome.WOULD_DENY
    assert decision.rule_id == "post-tool-missing-provenance"


def test_canary_is_hard_gated_in_enforce_mode() -> None:
    adapter = GovernanceAdapter(POLICY, mode=GovernanceMode.ENFORCE)
    with pytest.raises(GovernanceDenied) as exc:
        adapter.pre_output(
            agent_role=AgentRole.PROCUREMENT_ASSISTANT,
            plan_id="plan-1",
            response_text="SYNTHETIC-CANARY-DO-NOT-LEAK",
            ungrounded_product_or_code=False,
            missing_calculation_output=False,
            validation_not_passed=False,
            plan_not_ready=False,
        )
    assert exc.value.decision.rule_id == "pre-output-synthetic-canary"
