# Web／HostedAgent 再配布記録（2026-09-12）

整理後のmain（f2c7931）から既存のrg-ms-foundry-observability-verifyへ再配布した。Functions・APIM・EasyAuthの設定変更は行っていない。

| 対象 | 結果 |
|---|---|
| Web | web-procurement-observe-nkjm |
| Web deployment ID | 869aca8b-159c-4937-b344-aef0b74b663c |
| Web起動 | ARM RuntimeSuccessful、成功1・失敗0・起動中0、errors=null |
| Web ZIP | src/webapp-foundry-oauth/procurement-web-20260912-redeploy.zip（ユーザー指示によりGitへ同梱） |
| Web ZIP SHA-256 | 20ebf1c263a88a12380c80f3f46765f53910bdec229ab632ed473406188000d0 |
| Hosted | procurement-parent-agent v36、ACTIVE |
| Hosted ZIP SHA-256 | 668bdda9c721ca684278d413e3f6c47391236b4c637f7e44bd18e29ed0b8616a |

WebはLinux／Python 3.13用依存同梱ZIPを配布。既存のstartup.shとbuild無効設定を維持した。ZIPの1952ファイルに.envが含まれないことを確認し、今回同梱した依存によるWebテスト31件・subtest2件が成功した。

Hostedの直接呼出し（S1-DIRECT-20260912124718）はHTTP200、technical／MCP／Search／parseがSUCCESS、businessは追加入力待ちのWAITING_USER。Response IDはcaresp_05d589f4b3af2f38009FEnSEmx0MwKTV7sL7JEzrH9vFmhKo1W。

「私は誰ですか」の直接呼出しではoauth_consent_requestを返した。Response IDはcaresp_07cfd16f3c305f3600KGUHBCVv84tWkFk5V32poZOmfo14Gpo1。これは実ユーザーのGraph名取得成功とは別の確認である。

Webの未認証healthは401で、EasyAuth保護を維持。再配布後のサインイン済みWebで名前が表示されたことをユーザーが確認した。診断欄の表示については今回の返信では未確認。ユーザーの追加指示により、配布したZIPと本記録をレビューなしのPR経由でマージする。
