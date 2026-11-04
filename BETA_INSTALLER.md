# Livemetry Pulse ベータ版テストインストーラー

無料ベータ配布のテスト用に、リリース済み v1.6.0 と**完全に分離**された
ベータ版（`1.6.0-beta.1`）のビルド・配布手順です。
`installer_release.iss` と v1.6.0 の配布物は変更していません。

## 分離の仕組み

ベータ版の実体は「ベータ版フラグ（`beta_edition.flag`）が同梱された同じコード」です。
`core/app_edition.py` が起動直後（app.py の先頭、他の import より前）に次を行います。

- フラグがある（または環境変数 `LIVEMETRY_EDITION=beta`）場合のみベータ扱い
- `LOCALAPPDATA` を `<LOCALAPPDATA>\LivemetryPulseBeta` に付け替える（子プロセスへ継承、付け替えは1回だけ）
- keyring のサービス名に `-Beta` を付ける（`core/secure_storage.py`）

このアプリの保存先はすべて `LOCALAPPDATA` 由来のため、これだけで全データが分離されます。
フラグが無い通常ビルドでは**何も起きません**（従来どおりの動作）。

## 保存先の監査結果

| 保存物 | 通常版 | ベータ版 |
|---|---|---|
| settings.json（ライセンスキー含む） | `%LOCALAPPDATA%\AI-TikTok-LIVE-Analyzer\` | `%LOCALAPPDATA%\LivemetryPulseBeta\AI-TikTok-LIVE-Analyzer\` |
| 観測DB（capture / capture_fixed / battle_dataset） | 上記フォルダ配下 | ベータ配下（同左構造） |
| TopWatch 子データ | 上記配下 `top_watch\<id>\` | ベータ配下 |
| WebView2 プロファイル | 上記配下 | ベータ配下 |
| ログ（app.log 等） | 上記配下 `logs\` | ベータ配下 |
| レポート・AIレポート・証拠キャプチャ | 上記配下 | ベータ配下 |
| OpenAI APIキー（keyring） | サービス `AI-TikTok-LIVE-Analyzer` | サービス `AI-TikTok-LIVE-Analyzer-Beta`（別エントリ） |
| インストール先 | `%LOCALAPPDATA%\Programs\Livemetry Pulse` | `%LOCALAPPDATA%\Programs\Livemetry Pulse Beta` |
| AppId（Inno Setup） | `{A58F6A53-…}` | `{5F1D4EC2-…}`（別ID） |
| EXE名 | `LivemetryPulse.exe` | `LivemetryPulseBeta.exe` |

アンインストールで消えるのはベータのインストールフォルダだけです。
ベータのデータフォルダ（`%LOCALAPPDATA%\LivemetryPulseBeta`）は確認用に残ります。
不要になったら手動で削除してください。通常版のデータはそこには入りません。

## バージョン表記の一致

次の3か所がすべて `1.6.0-beta.1` で一致すること（`build_beta.bat` が自動チェックし、
不一致ならビルドを中止します）。

- `core/app_edition.py` の `BETA_VERSION_LABEL`（アプリ内表示 `v1.6.0-beta.1` の源）
- `version_info_beta.txt` の `ProductVersion` / `FileVersion`
- `installer_beta.iss` の `MyAppVersion`

## 秘密情報を同梱しないこと

- spec が同梱するのは `assets` 等の同梱フォルダと `beta_edition.flag`、`customtkinter` /
  `pywebview` のデータファイルだけです。`.env` は同梱されません（`.env.example` のみ、存在する場合）。
- settings.json やライセンス情報はリポジトリにも dist にも含まれません（実行時にユーザー側で生成）。
- インストーラーは `dist\LivemetryPulseBeta` の中身と `beta_edition.flag` だけを配布します。

## ビルド手順（Windows）

前提: Python 3.13、PyInstaller 6.22.3、Inno Setup 6。

```
cd /d <リポジトリ>
build_beta.bat
```

bat の処理: バージョン一致チェック → `requirements-build.txt` の依存をインストール
→ `LivemetryPulseBeta.spec` でビルド → `tools\smoke_test_beta.ps1` でスモークテスト
→ ISCC があれば `installer_beta.iss` からインストーラー生成
（`installer\LivemetryPulseBeta-Setup-v1.6.0-beta.1.exe`）。

## テスト

1. スモークテスト（ビルド後に自動実行、手動でも可）

   ```
   powershell -ExecutionPolicy Bypass -File tools\smoke_test_beta.ps1
   ```

   テスト用 LOCALAPPDATA で起動し、ベータ専用フォルダへの settings.json 生成、
   通常版フォルダを作らないこと、終了できること、実データ不変を確認します。

2. 分離検証（インストール〜アンインストールの実地確認）

   ```
   powershell -ExecutionPolicy Bypass -File tools\verify_beta_isolation.ps1
   ```

   サイレントインストール → 実環境のまま起動（データがベータ側にだけ作られること、
   通常版データのハッシュ・ファイル数が不変）→ サイレントアンインストール →
   通常版データ不変を再確認します。

3. 回帰テスト: `tools\run_regression.ps1`（エディション判定の単体テストは
   `tests\beta_edition_test.py`）。
