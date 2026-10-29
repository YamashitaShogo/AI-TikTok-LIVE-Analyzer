# 無人観測レポート 設計メモ（プラン・規約・将来連携）

この文書は `feature/unattended-observation-report` の設計判断を記録する。
実装本体は `core/observation_sessions.py`、`core/unattended_report.py`、
`core/report_export.py`、`core/report_ai.py`、`ui/pages/unattended_report.py`。

## MVP範囲の調整（理由付き）

1. **セッション開始・終了はレポート画面から明示操作する。**
   Battle Hunter / Top固定観測 / TopWatch は別プロセス・別プロファイルで
   動作しており、それらの開始経路すべてへ自動フックを差し込むと収集本体の
   変更範囲が大きくなる。既存の `collector_health.json` ハートビートを
   サンプリングして「実際に監視できた時間／接続中断」を実測する方式にしたため、
   収集コードには一切手を入れていない。将来、各コレクタの開始・停止地点から
   `SessionStore.start_session/stop_session` を呼ぶ配線を追加できる。
2. **TopWatch 子プロセスのデータは読み取り専用で参照する。**
   `top_watch/<streamer_id>/.../capture_fixed` の配置が「フォルダ名＝観測対象」を
   検証できる場合のみ集計対象に含めた（`available_sources`）。セッションの
   開始・停止は子プロセス側の責務とし、親画面からは操作しない。
3. **PDF のグラフは代表バトル方式。**
   全バトルのグラフを PDF に並べるとページ数が膨らむため、視聴者サンプル数が
   最多のバトルを「代表バトル」と明記して掲載する。全バトルの推移はアプリ内
   「推移」タブと JSON で確認できる。

## 観測セッション設計

- 保存先は分離: `<capture>/observation_report/sessions.sqlite3`。
  既存の battles DB には書き込まない。
- 異常終了・停電時は、次回起動時に `running` のまま残ったセッションを
  `interrupted` として検出する。終了時刻は推測で確定させず `ended_at` は
  NULL のままにし、最後の heartbeat 時刻を証拠として保持する。
- 監視できた時間は heartbeat サンプルの実測累積。サンプリング間隔を
  超えた空白は `gap_seconds`（不明）として分離する。

## プラン別機能制御（設計のみ・未有効化）

`core/report_plans.py` に機能キーと想定プランの対応を定義した。
現段階では enforcement は既定 OFF で、すべての機能が利用できる。
課金判定・決済は今回のスコープ外。

| 機能キー | 内容 | 想定プラン |
|---|---|---|
| report.basic | 基本統計レポート | Free |
| report.charts | スコア・視聴者数グラフ | Free |
| report.json_csv | JSON / CSV 出力 | Free |
| report.pdf | PDF出力 | Pro |
| report.compare | 前回レポートとの比較 | Pro |
| report.ai | AI改善提案 | Pro |
| report.multi_streamer | 複数配信者の比較レポート | Agency（将来） |
| report.agency_rollup | 事務所向け集計 | Agency（将来） |

既存のライセンス認証（`core/license_client.py`）の仕様は変更していない。
将来プラン判定を入れる場合は、ライセンスサーバーの応答にプランを含め、
`feature_allowed()` の呼び出し側でだけ制御する想定。

## PR #7（画面証拠）との将来連携

PR #7 が未マージのため、本機能は独立実装とした。連携用の受け口だけ用意した:

- セッションの `evidence_refs_json`（初期値 `[]`）: 観測セッションと
  証拠セッション（`<battle_id>_<observation_id>`）の紐付けを将来格納する。
- レポート JSON の `evidence_links`（初期値 `[]`）: スコア変動時刻と
  保存画像、人間による確認結果（human_verdict）への参照を将来格納する。
- ファーストチャレンジ ×3 は現在 **UNKNOWN**。推測による確定判定は
  実装していないし、この受け口にも自動判定は入れない。

## TikTok データに関する販売前の確認項目（チェックリスト）

以下は本機能の実装では判断しない。販売前に別途確認すること:

- [ ] TikTok 利用規約・開発者ポリシーにおける、LIVE データの取得・保存・
      商用利用の可否と範囲
- [ ] 観測対象の配信者から、データ取得とレポート利用についての同意を
      得る運用（特に他者の配信を観測して販売レポート化する場合）
- [ ] 保存データ（コメント・視聴者数・スコア等）の保持期間と削除ポリシー
- [ ] 個人情報（@ID・ニックネーム等）を外部送信・共有する際の取り扱い
- [ ] 「TikTok 公式サービスとの提携・認可がある」と誤認させる表現を
      使っていないこと（本レポートの PDF には非提携である旨を明記した）
