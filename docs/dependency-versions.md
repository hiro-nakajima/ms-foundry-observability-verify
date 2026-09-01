# Dependency versions

Local検証環境はPython 3.13.13を使用した。runtimeの主要pinは次のとおり。

| Package | Version | 用途 |
|---|---:|---|
| `agent-framework-core` | 1.16.0 | Agent、AgentSession、History Provider、Middleware、Agent Tool |
| `agent-framework-foundry` | 1.11.0 | 登録済みPrompt Agentの`FoundryAgent` proxy |
| `agent-framework-foundry-hosting` | 1.0.0b260827 | Responses host |
| `agent-framework-devui` | 1.0.0b260821 | Local DevUI |
| `agent-framework-openai` | 1.14.1 | Framework/Foundry runtime dependency |
| `azure-ai-projects` | 2.3.0 | Foundry project client dependency |
| `azure-ai-inference` | 1.0.0b9 | Foundry integration dependency |
| `pydantic` | 2.13.4 | ExecutionPlanとStructured I/O |

採用signatureはLocal installed packageで確認し、`tests/unit/test_hosted_factory_v2.py`と`tests/unit/test_session_state_v2.py`をcontract testとして固定した。特に`AgentSession.to_dict/from_dict`、`InMemoryHistoryProvider(..., load_messages=True)`、`FunctionInvocationContext.session`、`FoundryAgent.as_tool(propagate_session=False)`を検証対象とする。
