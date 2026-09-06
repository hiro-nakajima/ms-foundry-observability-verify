# Known limitations

現行Azure配備と検証statusは[2026-09-06 validation report](report/validation-results-2026-09-06.md)を正とする。

- S1～S5はAzureで代表的な正常/自然負例を実測したが、Core Matrix全caseとHealthy detector照合はPARTIALである。
- Stage A 14 Failure PatternはLocal contract 14/14。Stage Bの`TV-02/03`、`SD-03/05`、`MA-04/05`はAzure injection未実施で`AZURE_PENDING`である。
- Managed境界では`traceparent`が同一TraceになるcaseとPrompt子が別Traceになるcaseがある。別Traceはresponse ID/Conversation IDで相関し、`NOT_PROPAGATED`をPASSへ変更しない。
- 仮名化`user.id` baggageはApp Serviceの送信まで実測済みだが、Hosted/Prompt/Toolboxでは取得できず`NOT_PROPAGATED`である。
- APIM内部spanとSearch service内部spanは`NOT_RECORDED_BY_PLATFORM`。Toolbox envelopeをSearch engine内部spanとして扱わない。
- Hostedのcontent captureをfalseにしてもManaged Prompt子のinput/output contentが記録され得る。`AppGenAIContent` Protected applyはread-backへ反映されずGeneral相当/90日のため、Synthetic以外を流す前のprivacy blockerである。
- Code子の一般化した`NOT_FOUND`では、親が「部署未登録」と「勘定科目/分類mapping未登録」を常に分離できず、後者でも部署再入力を求める場合がある。draftは作らずfail-closedする。
- partial intakeを持つSessionへ通常Hosted経路を通さず完全`ProcurementRequest`を直接送る外部callerは、confirmationでなくても`confirmation_state_invalid`になり得る。
- Serverless Developerはpreview/SLAなし。Searchのcold latency寄与は専用A/B未測定だが、現行Traceでは親/子LLM区間が主因である。
- Functions OBO参考経路とOAuth参考Web backendはsourceのみ。現行購買E2Eへは未配備で、Graph `/me`のAzure再検証も未実施である。
