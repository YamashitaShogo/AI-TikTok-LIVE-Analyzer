# Livemetry Pulse — データスナップショット共通処理
# smoke_test_beta.ps1 / verify_beta_isolation.ps1 から dot-source して使う。
#
# Get-FullSnapshot: フォルダ配下の全ファイルについて
# 「相対パス|サイズ|SHA256」をソートして連結した文字列を返す。
#
# 例外 (SQLite の *-shm):
#   -shm は共有メモリファイルで、OSにマップされていると Get-FileHash で
#   読めないことがある（プロセスが検出されなくても発生する）。また中身は
#   再起動で再生成される一時データであり、「観測データそのもの」ではない。
#   そのため比較対象から除外し、除外したファイルは呼び出し側が
#   診断ログへ明記する（戻り値の Excluded）。
# 保護対象 (.sqlite3 本体と *-wal):
#   読み取れない場合、またはハッシュ取得の前後でサイズ/更新時刻が
#   変わった（比較途中で変更された）場合は、例外を投げて安全に
#   失敗させる。ファイルを削除したりは一切しない。
function Get-FullSnapshot([string]$Dir) {
    if (-not (Test-Path $Dir)) { return @{ Text = '<absent>'; Count = -1; Excluded = @() } }
    $lines = @()
    $excluded = @()
    foreach ($file in (Get-ChildItem $Dir -Recurse -File -ErrorAction SilentlyContinue)) {
        $rel = $file.FullName.Substring($Dir.Length)
        if ($file.Name -like '*-shm') {
            $excluded += $rel
            continue
        }
        $lengthBefore = $file.Length
        $timeBefore = $file.LastWriteTimeUtc
        try {
            $hash = (Get-FileHash $file.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
        } catch {
            throw "スナップショット失敗: ファイルを読み取れません: $($file.FullName) — $($_.Exception.Message)"
        }
        $after = Get-Item $file.FullName -ErrorAction Stop
        if ($after.Length -ne $lengthBefore -or $after.LastWriteTimeUtc -ne $timeBefore) {
            throw "スナップショット失敗: 比較途中でファイルが変更されました: $($file.FullName)"
        }
        $lines += ('{0}|{1}|{2}' -f $rel, $lengthBefore, $hash)
    }
    $sorted = @($lines | Sort-Object)
    return @{ Text = ($sorted -join "`n"); Count = $sorted.Count; Excluded = $excluded }
}
