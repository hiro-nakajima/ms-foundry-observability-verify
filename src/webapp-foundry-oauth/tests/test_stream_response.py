from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import server  # noqa: E402


def _stream_lines(*events: dict) -> list[str]:
    lines: list[str] = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}")
        lines.append("")
    lines.extend(["data: [DONE]", ""])
    return lines


class _FakeResponse:
    status_code = 200

    def __init__(self, lines: list[str]):
        self._lines = lines
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited = True

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.request_json: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def stream(self, method, url, *, headers, json):
        self.request_json = json
        return self.response


class StreamResponseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        server._conversations.clear()

    def test_token_log_projection_contains_presence_flags_only(self):
        claims = {
            "aud": "api://resource",
            "tid": "raw-tenant",
            "oid": "raw-user",
            "preferred_username": "person@example.invalid",
            "scp": "User.Read",
            "exp": 1234567890,
        }

        projected = server._sanitize_token_claims(claims)

        self.assertTrue(projected["audience_present"])
        self.assertTrue(projected["tenant_present"])
        self.assertTrue(projected["user_present"])
        self.assertTrue(projected["scopes_present"])
        self.assertTrue(projected["expiry_present"])
        self.assertFalse(
            any(value in projected.values() for value in claims.values())
        )

    async def _first_event(self, response: _FakeResponse, conversation_id: str):
        client = _FakeAsyncClient(response)
        with patch.object(server.httpx, "AsyncClient", return_value=client):
            stream = server._stream_response(
                project_endpoint="https://example.test/api/projects/project",
                agent_name="agent",
                user_message="whoami",
                previous_response_id=None,
                approval_inputs=None,
                conversation_id=conversation_id,
                outbound_headers={"Authorization": "Bearer test"},
            )
            first_payload = await anext(stream)
            with self.assertRaises(StopAsyncIteration):
                await anext(stream)
        parsed = server._parse_sse_payload(first_payload)
        self.assertIsNotNone(parsed)
        return parsed

    async def test_mcp_approval_is_published_after_completed_stream_is_closed(self):
        response = _FakeResponse(
            _stream_lines(
                {
                    "type": "response.created",
                    "response": {"id": "resp_approval"},
                },
                {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "mcp_approval_request",
                        "id": "mcpr_123",
                        "server_label": "whoami_func",
                        "name": "whoami",
                        "arguments": "{}",
                    },
                },
                {
                    "type": "response.completed",
                    "response": {"id": "resp_approval", "output": []},
                },
            )
        )

        event = await self._first_event(response, "approval-conversation")

        self.assertTrue(response.exited)
        self.assertEqual(event["type"], "mcp_approval_required")
        self.assertEqual(event["responseId"], "resp_approval")
        self.assertEqual(
            server._conversations["approval-conversation"],
            {
                "previous_response_id": "resp_approval",
                "pending_approvals": [
                    {
                        "id": "mcpr_123",
                        "serverLabel": "whoami_func",
                        "toolName": "whoami",
                        "arguments": "{}",
                    }
                ],
                "awaiting_consent": False,
            },
        )

    async def test_oauth_consent_is_published_after_completed_stream_is_closed(self):
        response = _FakeResponse(
            _stream_lines(
                {
                    "type": "response.created",
                    "response": {"id": "resp_consent"},
                },
                {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "oauth_consent_request",
                        "consent_link": "https://login.example.test/consent",
                        "server_label": "whoami_func",
                    },
                },
                {
                    "type": "response.completed",
                    "response": {"id": "resp_consent", "output": []},
                },
            )
        )

        event = await self._first_event(response, "consent-conversation")

        self.assertTrue(response.exited)
        self.assertEqual(event["type"], "oauth_consent_required")
        self.assertEqual(event["responseId"], "resp_consent")
        self.assertEqual(
            server._conversations["consent-conversation"],
            {
                "previous_response_id": "resp_consent",
                "pending_approvals": [],
                "awaiting_consent": True,
                "pending_consent": {
                    "consentLink": "https://login.example.test/consent",
                    "connectionName": "whoami_func",
                },
            },
        )

    async def test_parallel_mcp_approvals_are_collected_and_deduplicated(self):
        response = _FakeResponse(
            _stream_lines(
                {
                    "type": "response.created",
                    "response": {"id": "resp_parallel_approvals"},
                },
                {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "mcp_approval_request",
                        "id": "mcpr_first",
                        "server_label": "first_server",
                        "name": "first_tool",
                        "arguments": '{"first": true}',
                    },
                },
                {
                    "type": "mcp_approval_request",
                    "id": "mcpr_second",
                    "server_label": "second_server",
                    "name": "second_tool",
                    "arguments": '{"second": true}',
                },
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "mcp_approval_request",
                        "id": "mcpr_first",
                        "server_label": "first_server",
                        "name": "first_tool",
                        "arguments": '{"first": true}',
                    },
                },
                {
                    "type": "response.completed",
                    "response": {"id": "resp_parallel_approvals", "output": []},
                },
            )
        )

        event = await self._first_event(response, "parallel-approval-conversation")

        self.assertTrue(response.exited)
        self.assertEqual(event["type"], "mcp_approval_required")
        self.assertEqual(
            event["approvalRequestIds"], ["mcpr_first", "mcpr_second"]
        )
        self.assertEqual(
            event["pendingApprovals"],
            [
                {
                    "approvalRequestId": "mcpr_first",
                    "serverLabel": "first_server",
                    "toolName": "first_tool",
                    "arguments": '{"first": true}',
                },
                {
                    "approvalRequestId": "mcpr_second",
                    "serverLabel": "second_server",
                    "toolName": "second_tool",
                    "arguments": '{"second": true}',
                },
            ],
        )
        self.assertEqual(
            server._conversations["parallel-approval-conversation"][
                "pending_approvals"
            ],
            [
                {
                    "id": "mcpr_first",
                    "serverLabel": "first_server",
                    "toolName": "first_tool",
                    "arguments": '{"first": true}',
                },
                {
                    "id": "mcpr_second",
                    "serverLabel": "second_server",
                    "toolName": "second_tool",
                    "arguments": '{"second": true}',
                },
            ],
        )

    async def test_approval_and_consent_are_preserved_regardless_of_event_order(self):
        approval_event = {
            "type": "response.output_item.added",
            "item": {
                "type": "mcp_approval_request",
                "id": "mcpr_mixed",
                "server_label": "approval_server",
                "name": "approval_tool",
                "arguments": '{"approved": true}',
            },
        }
        consent_event = {
            "type": "response.output_item.added",
            "item": {
                "type": "oauth_consent_request",
                "consent_link": "https://login.example.test/mixed-consent",
                "server_label": "consent_server",
            },
        }

        for suffix, action_events in (
            ("approval-first", (approval_event, consent_event)),
            ("consent-first", (consent_event, approval_event)),
        ):
            with self.subTest(order=suffix):
                conversation_id = f"mixed-{suffix}"
                response = _FakeResponse(
                    _stream_lines(
                        {
                            "type": "response.created",
                            "response": {"id": f"resp_{suffix}"},
                        },
                        *action_events,
                        {
                            "type": "response.completed",
                            "response": {"id": f"resp_{suffix}", "output": []},
                        },
                    )
                )

                event = await self._first_event(response, conversation_id)

                self.assertEqual(event["type"], "mcp_approval_required")
                self.assertEqual(event["approvalRequestIds"], ["mcpr_mixed"])
                self.assertEqual(
                    server._conversations[conversation_id],
                    {
                        "previous_response_id": f"resp_{suffix}",
                        "pending_approvals": [
                            {
                                "id": "mcpr_mixed",
                                "serverLabel": "approval_server",
                                "toolName": "approval_tool",
                                "arguments": '{"approved": true}',
                            }
                        ],
                        "awaiting_consent": True,
                        "pending_consent": {
                            "consentLink": "https://login.example.test/mixed-consent",
                            "connectionName": "consent_server",
                        },
                    },
                )

    async def test_consent_payload_is_published_after_approval_continuation(self):
        server._conversations["carried-consent-conversation"] = {
            "previous_response_id": "resp_mixed",
            "pending_approvals": [
                {
                    "id": "mcpr_mixed",
                    "serverLabel": "approval_server",
                    "toolName": "approval_tool",
                    "arguments": "{}",
                }
            ],
            "awaiting_consent": True,
            "pending_consent": {
                "consentLink": "https://login.example.test/carried-consent",
                "connectionName": "consent_server",
            },
        }
        response = _FakeResponse(
            _stream_lines(
                {
                    "type": "response.created",
                    "response": {"id": "resp_after_approval"},
                },
                {
                    "type": "response.completed",
                    "response": {"id": "resp_after_approval", "output": []},
                },
            )
        )
        client = _FakeAsyncClient(response)
        with patch.object(server.httpx, "AsyncClient", return_value=client):
            stream = server._stream_response(
                project_endpoint="https://example.test/api/projects/project",
                agent_name="agent",
                user_message=None,
                previous_response_id="resp_mixed",
                approval_inputs=[
                    {
                        "type": "mcp_approval_response",
                        "approve": True,
                        "approval_request_id": "mcpr_mixed",
                    }
                ],
                conversation_id="carried-consent-conversation",
                outbound_headers={"Authorization": "Bearer test"},
            )
            first_payload = await anext(stream)
            with self.assertRaises(StopAsyncIteration):
                await anext(stream)

        event = server._parse_sse_payload(first_payload)
        self.assertEqual(
            event,
            {
                "type": "oauth_consent_required",
                "consentLink": "https://login.example.test/carried-consent",
                "connectionName": "consent_server",
                "responseId": "resp_after_approval",
            },
        )
        self.assertEqual(
            server._conversations["carried-consent-conversation"],
            {
                "previous_response_id": "resp_after_approval",
                "pending_approvals": [],
                "awaiting_consent": True,
                "pending_consent": {
                    "consentLink": "https://login.example.test/carried-consent",
                    "connectionName": "consent_server",
                },
            },
        )

    async def test_incomplete_stream_does_not_publish_actionable_state(self):
        response = _FakeResponse(
            _stream_lines(
                {
                    "type": "response.created",
                    "response": {"id": "resp_incomplete"},
                },
                {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "mcp_approval_request",
                        "id": "mcpr_incomplete",
                        "server_label": "whoami_func",
                        "name": "whoami",
                        "arguments": "{}",
                    },
                },
            )
        )

        event = await self._first_event(response, "incomplete-conversation")

        self.assertTrue(response.exited)
        self.assertEqual(event["type"], "error")
        self.assertNotIn("incomplete-conversation", server._conversations)

    async def test_normal_completed_response_advances_conversation(self):
        response = _FakeResponse(
            _stream_lines(
                {
                    "type": "response.created",
                    "response": {"id": "resp_done"},
                },
                {
                    "type": "response.completed",
                    "response": {"id": "resp_done", "output": []},
                },
            )
        )

        event = await self._first_event(response, "done-conversation")

        self.assertTrue(response.exited)
        self.assertEqual(event, {"type": "done", "responseId": "resp_done"})
        self.assertEqual(
            server._conversations["done-conversation"],
            {
                "previous_response_id": "resp_done",
                "pending_approvals": [],
                "awaiting_consent": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
