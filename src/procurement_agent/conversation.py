"""Natural-language intake and human-readable DevUI presentation.

This module deliberately extracts only values stated by the user.  Product
codes, prices, account codes, delivery estimates, and totals remain owned by
the structured tool and skill boundaries.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Iterable
from uuid import uuid4

from .intake import ProcurementRequestPatch
from .memory import AgentSession
from .models import PlanStatus, ProcurementRequest


def merge_natural_request(
    patch: ProcurementRequestPatch,
    *,
    current: ProcurementRequest | None = None,
    pending: dict[str, Any] | None = None,
) -> tuple[ProcurementRequest | None, dict[str, Any]]:
    """Merge a turn patch without clearing values collected on earlier turns."""

    merged: dict[str, Any] = current.model_dump(mode="json") if current else dict(pending or {})
    patch_data = patch.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    patch_constraints = patch_data.pop("constraints", {})
    specification_entries = patch_constraints.get("specifications")
    if isinstance(specification_entries, list):
        patch_constraints["specifications"] = {
            entry["key"]: entry["value"]
            for entry in specification_entries
        }
    merged.update(patch_data)
    constraints = dict(merged.get("constraints") or {})
    constraints.update(patch_constraints)
    merged["constraints"] = constraints
    merged.setdefault("request_id", f"REQ-DEVUI-{uuid4().hex[:8].upper()}")
    if not merged.get("query"):
        return None, merged
    return ProcurementRequest.model_validate(merged), merged


def natural_missing_required_fields(request: ProcurementRequest) -> list[str]:
    """Required intake order for a conversational procurement request."""

    missing: list[str] = []
    if request.quantity is None:
        missing.append("quantity")
    if not request.department_name:
        missing.append("department_name")
    if not request.applicant_name:
        missing.append("applicant_name")
    if not request.purpose:
        missing.append("purpose")
    if request.constraints.requested_by is None:
        missing.append("constraints.requested_by")
    return missing


FIELD_LABELS = {
    "quantity": "数量（例: 3台）",
    "applicant_name": "申請者名または社員ID",
    "department_name": "部門名または部門コード（例: 情報シス）",
    "purpose": "用途（例: 開発）",
    "constraints.requested_by": "希望納期（YYYY-MM-DD）",
    "request.query": "購入したい商品",
    "request.constraints.specifications": "商品を特定できる仕様",
}

STEP_LABELS = {
    "parse_request": "依頼内容を構造化する",
    "resolve_missing_fields": "不足情報を確認する",
    "search_catalog": "商品カタログを検索する",
    "select_catalog_item": "商品・商品コード・単価を確定する",
    "get_applicant": "申請者を照会する",
    "lookup_department": "部門コードを照会する",
    "lookup_account_code": "勘定科目コードを照会する",
    "estimate_delivery": "納期を照会する",
    "calculate_total": "計算 Script で金額を算出する",
    "build_draft": "申請ドラフトを作成する",
    "validate_draft": "申請ドラフトを検証する",
    "confirm_application": "申請内容をユーザーが確定する",
    "present_draft": "検証済みドラフトを提示する",
    "procurement_lookup": "調達担当へ商品・商品コード・単価・納期等の照会を委譲する",
    "merge_procurement_result": "調達結果を Coordinator Session に統合する",
    "merge_draft_result": "起案結果を Coordinator Session に統合する",
}


def format_product_question() -> str:
    return (
        "購買申請を開始します。まず、購入したい商品を教えてください。\n\n"
        "その後、依頼の構造化 → 不足情報確認 → カタログ・申請者・部門・"
        "勘定科目・納期の照会 → Script 計算 → 起案 → 検証 → 提示、の順に進めます。"
    )


def format_department_clarification(
    options: Iterable[dict[str, str]],
    session: AgentSession,
    status_summary: dict[str, Any] | None = None,
) -> str:
    lines = [
        "部門を一意に特定できませんでした。次のどちらかを選択してください。",
        "",
    ]
    for index, option in enumerate(options, start=1):
        lines.append(
            f"{index}. {option['name']}（`{option['department_code']}`）"
        )
    lines.append("")
    lines.append("正式な部門名、部門コード、または `1部` / `2部` と入力できます。")
    summary = status_summary or {}
    lines.append(f"Plan ID: `{session.plan.plan_id}` / 状態: `WAITING_USER`")
    if trace_id := summary.get("trace_id"):
        lines.append(f"Trace ID: `{trace_id}`")
    return "\n".join(lines)


def format_natural_outcome(
    response_text: str,
    session: AgentSession,
    status_summary: dict[str, Any] | None = None,
) -> str:
    """Render application-owned machine output for a conversational DevUI turn."""

    payload = json.loads(response_text)
    status = payload.get("business_status")
    if status == "WAITING_USER":
        lines = ["購買申請の実行計画を作成しました。", "", "**実行ステップ**"]
        for index, step in enumerate(session.plan.steps, start=1):
            marker = {
                PlanStatus.COMPLETED: "完了",
                PlanStatus.WAITING_USER: "入力待ち",
                PlanStatus.RUNNING: "実行中",
                PlanStatus.BLOCKED: "停止",
                PlanStatus.FAILED: "失敗",
                PlanStatus.INVALIDATED: "再実行予定",
            }.get(step.status, "待機")
            lines.append(f"{index}. [{marker}] {STEP_LABELS.get(step.step_type, step.step_type)}")
        if payload.get("confirmation_required"):
            lines.extend(["", "**検証済み申請内容**", *_draft_lines(payload["application_draft"])])
            lines.extend(
                [
                    "",
                    "内容を確認し、申請内容を確定する場合は **`確定`** と入力してください。",
                    "条件を変更する場合は、確定せず変更内容を入力してください。",
                ]
            )
            summary = status_summary or {}
            lines.extend(
                ["", f"Plan ID: `{session.plan.plan_id}` / 状態: `WAITING_USER`"]
            )
            if trace_id := summary.get("trace_id"):
                lines.append(f"Trace ID: `{trace_id}`")
            delegations = summary.get("delegations") or []
            if delegations:
                lines.append(
                    "Agent Tool 委譲: "
                    + " → ".join(f"`{role}`" for role in delegations)
                )
            return "\n".join(lines)

        clarification = payload.get("clarification") or {}
        missing = list(payload.get("missing_required_fields") or [])
        if clarification:
            prompt = clarification.get("prompt", "追加条件を教えてください。")
            lines.extend(["", f"**次に必要な回答**: {prompt}"])
            options = clarification.get("options") or []
            if options:
                lines.append("候補: " + " / ".join(_format_option(item) for item in options))
        elif missing:
            next_field = missing[0]
            lines.extend(
                ["", "**次に必要な回答**: " + FIELD_LABELS.get(next_field, next_field)]
            )
            if len(missing) > 1:
                lines.append(f"この後に確認する項目: {len(missing) - 1}件")
            lines.append("複数項目を一度に回答することもできます。")
        summary = status_summary or {}
        lines.extend(["", f"Plan ID: `{session.plan.plan_id}` / 状態: `WAITING_USER`"])
        if trace_id := summary.get("trace_id"):
            resumed = summary.get("session_resumed", False)
            lines.append(f"Trace ID: `{trace_id}` / Session resume: `{resumed}`")
        return "\n".join(lines)

    if status == "SUCCESS" and payload.get("validated"):
        draft = payload["application_draft"]
        observability = payload.get("observability", {})
        lines = [
            (
                "購買申請内容を確定しました。"
                if payload.get("confirmed")
                else "検証済みの購買申請ドラフトを作成しました。"
            ),
            "",
            *_draft_lines(draft),
            "",
            f"検証: `PASS` / Plan: "
            f"`{observability.get('plan_status', 'COMPLETED')}` / "
            f"Trace ID: `{observability.get('trace_id', '')}`",
            f"Session resume: `{observability.get('session_resumed', False)}`",
        ]
        delegations = observability.get("delegations") or []
        if delegations:
            lines.append(
                "Agent Tool 委譲: " + " → ".join(f"`{role}`" for role in delegations)
            )
        decisions = observability.get("governance_decisions") or []
        if decisions:
            lines.append("Governance: " + ", ".join(decisions))
        warnings = observability.get("warnings") or []
        if warnings:
            lines.append("Warning: " + "; ".join(warnings))
        return "\n".join(lines)

    message = payload.get("message") or payload.get("failed_tool") or "処理を継続できませんでした。"
    return (
        f"購買申請は業務状態 `{status or 'UNKNOWN'}` で停止しました。\n\n"
        f"詳細: {message}\n\n入力条件を変更して、もう一度依頼してください。"
    )


def _draft_lines(draft: dict[str, Any]) -> list[str]:
    item = draft["item"]
    amount = draft["amount"]
    applicant = draft["applicant"]
    account = draft["account"]
    delivery = draft["delivery"]
    return [
        f"- 商品: {item['name']}",
        f"- 商品コード: `{item['product_code']}`",
        f"- 単価: {int(Decimal(item['unit_price'])):,} {item['currency']}",
        f"- 数量: {item['quantity']}",
        f"- 小計: {int(Decimal(amount['subtotal'])):,} JPY",
        f"- 税額: {int(Decimal(amount['tax'])):,} JPY",
        f"- 合計: **{int(Decimal(amount['total'])):,} JPY**",
        f"- 納期見込: {delivery['estimated_on']}（希望納期内: "
        f"{'はい' if delivery['meets_request'] else 'いいえ'}）",
        f"- 申請者: {applicant['name']} / "
        f"部門コード: `{applicant['department_code']}`",
        f"- 勘定科目: {account['label']} / `{account['account_code']}`",
    ]


def _format_option(option: dict[str, Any]) -> str:
    return str(
        option.get("name")
        or option.get("product_code")
        or option.get("department_code")
        or option
    )
