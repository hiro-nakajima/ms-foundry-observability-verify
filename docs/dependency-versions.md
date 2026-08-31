# Dependency Versions and Compatibility

確認日: **2026-08-31**

Runtime dependencyは`requirements.txt`へ直接pinし、解決済みVersionを
`requirements-lock.txt`へ制約として保存しています。Test dependencyは
`requirements-dev.txt`です。`pyproject.toml`の一覧はwheel metadata用のmirrorで、
同期Testにより差分を検出します。

| Package | Pin | 選定理由 |
|---|---:|---|
| `agent-framework-core` | `1.16.0` | 確認日時点のcurrent release。Pydantic `response_format`、Session serialize/restore、ContextProvider、SkillsProvider、`Agent.as_tool()`を使用するため。全providerを含むmeta packageは不要なので採用しない。 |
| `agent-framework-devui` | `1.0.0b260821` | HA-S / HA-Mを同じFactoryからDevUIで起動するため。 |
| `agent-framework-foundry-hosting` | `1.0.0b260827` | Agent Framework 1.16.0と同じ解決集合で提供されるResponses hosting package。 |
| `agent-framework-openai` | `1.14.1` | Azure OpenAI Responses APIとPydantic `BaseModel`のStructured Outputで自然言語Turnを抽出するため。core `>=1.15,<2`制約と1.16.0の互換を確認。 |
| `azure-identity` | `1.26.0b2` | Local Azure CLI / Hosted Managed Identityを同じ`DefaultAzureCredential` chainで扱うため。 |
| `azure-ai-agentserver-core` | `2.1.0` | 上記hosting packageのlock済みtransitive dependency。 |
| `agent-governance-toolkit[core]` | `4.1.0` | 4-stage Policy EngineとOTel policy evaluationを使用するため。 |
| `opentelemetry-api` / `sdk` | `1.43.0` | Agent Framework hosting dependency setと互換な最新解決Version。 |
| `pydantic` | `2.13.4` | Domain、Plan、Agent Tool I/O、Trace Envelopeを同じSchema基盤にするため。 |
| `PyYAML` | `6.0.3` | version付きGovernance policy読み込み。 |
| `pytest` | `9.1.1` | Local Unit / Contract / Trace / Integration test。 |

## Compatibility decisions

- `requires-python`は`>=3.13,<3.15`、推奨開発Versionは`.python-version`の3.13です。Foundry source-code deploymentの`runtime: python_3_13`と一致させます。3.14はpackage互換確認用に許可しますが、source-code deployment runtimeには指定しません。
- Python 3.13.13と3.14.4の両環境で同じLocal Suite（148 passed / external 1 skipped）を実行済みです。
- Container Hosted Agentは独自image内のPythonを使えますが、本Repositoryはsource-code deploymentとの共通化を優先して3.13へ上げました。
- Runtime installは`python -m pip install -r requirements.txt`、開発環境は`requirements-dev.txt`を使用します。`uv.lock`は使用しません。
- `Agent.as_tool()`のdefaultと実装を確認し、HA-Mは明示的に`propagate_session=False`です。
- `AgentPlanResponse`をPlannerだけの`response_format`にし、同じInvocationのTool countが0であることをtestします。
- 自然言語受付は`ProcurementTurnExtraction(BaseModel)`だけを`response_format`へ指定し、Toolを登録しない独立Invocationにします。空Structured Outputは以前のTurnで補完せず、現在の不足項目を再質問します。
- OpenAI strict Structured Outputは任意keyの`dict[str, str]`を受理しないため、商品仕様は閉じた`SpecificationPatch(BaseModel)`の配列として受け、validation後にDomainのmappingへ変換します。
- Azure OpenAI `gpt-5-mini` version `2025-08-07`でStructured Output smokeを実施しました。reasoning effortはこのversionが受理する`minimal`を使用し、Invocationは`asyncio.timeout()`で90秒に制限します。
- Agent Framework `AgentSession.to_dict()/from_dict()`の後に`WAITING_USER` Planを再開するtestがあります。
- `SkillsProvider`は許可済みScript runnerと組み合わせ、HA-M子Agentのstructured JSON I/Oをstreaming経路でtestします。
- 旧`azure-ai-agentserver-agentframework==1.0.0b17`はAgent Framework 1.16.0とdependency rangeが競合するため採用せず、lockfileから除外しました。
- Agent Governance Toolkit 4.1.0の互換re-exportは実行時にdeprecated warningを出します。Policy評価自体はtest済みですが、公開import pathの移行はupstream guidance確認後に行います。

## Official sources checked

- [Agent Framework PyPI](https://pypi.org/project/agent-framework/)
- [Agent Framework Agent Tools](https://learn.microsoft.com/en-us/agent-framework/agents/tools/)
- [Agent Framework Skills](https://learn.microsoft.com/en-us/agent-framework/agents/skills)
- [Agent Framework Session](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/session)
- [Agent Framework Structured Outputs](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs)
- [Agent Framework OpenAI integration](https://github.com/microsoft/agent-framework/blob/main/python/packages/openai/README.md)
- [Agent Framework Runtime Context](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/middleware/runtime-context)
- [Agent Governance Toolkit PyPI](https://pypi.org/project/agent-governance-toolkit/)
- [Multi-stage Policy Pipeline](https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/tutorials/37-multi-stage-pipeline.md)
- [AGT OTel Observability](https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/tutorials/40-otel-observability.md)

Versionは時間とともに変わるため、Azure deployment Task開始時に再確認します。
