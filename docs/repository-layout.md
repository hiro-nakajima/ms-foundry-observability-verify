# リポジトリ整理記録

2026-09-12のWeb／Hosted改善後に構成を整理した。今回の変更はローカル配置と資料の整理であり、Azureへの再配布・基盤変更は実行していない。

## 配置変更

| 以前 | 現在・理由 |
|---|---|
| root main.py／requirements.txt／requirements-lock.txt／requirements-dev.txt／pyproject.toml | `src/hosted-agent/`へ集約。Hostedの入口と依存を同じ場所にする |
| `src/procurement_agent/` | `src/hosted-agent/procurement_agent/`。import名は変更しない |
| `src/trace_pipeline/` | `src/hosted-agent/trace_pipeline/`。Hosted評価拡張として同じcomponentへ置く |
| root pyproject内pytest設定 | 共通`pytest.ini`。横断テストのためrootに残す |
| rootの旧.env.example | 廃止済み構成の変数を含むため削除。Hostedの現行例を新規作成 |
| Functions pyproject.toml | 配布にもローカル起動にも使われず、requirementsと重複・不一致のため削除 |
| Web backend/.env.template | root .env.exampleと重複するため削除。個人の.envは保持 |

共通のscripts、infra、data、tests、trace_fixtures、azure.yaml、.foundryは用途があるため保持する。仮想環境、個人.env、.local_state、配布ZIP、未追跡の成果物は利用中かどうかをコードだけで断定できないため削除しない。

## 資料

現行手順は各component READMEへ集約。統合READMEは移植案内、deploymentは基盤の詳細、report／日付付き検証記録は証跡として保持する。仕様正本と14 Failure Patternは維持する。旧構成・タスク指示・旧ソース索引は[trash一覧](trash/README.md)へ退避した。

リンクは移動後の場所へ更新し、現行資料のローカル絶対パスリンクを相対パス化した。trash内の古い数値・hash・当時のコマンドは履歴であり、現在の手順として使用しない。

## 確認

- 新配置で既存テスト246件が成功、外部Azure E2Eは1件スキップ。
- 梱包テストでZIP展開後のmain.py --smokeを確認。
- Azure向けの依存・実行コードの内容は配置変更で変えない。
- 新たなAzure配布、VS Code拡張による実配布は未実施。
