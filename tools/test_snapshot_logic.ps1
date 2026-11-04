# Livemetry Pulse — スナップショット処理の単体テスト
# tools/snapshot_lib.ps1 の Get-FullSnapshot を、一時フォルダ上の
# ダミーデータで検証します。実データには一切触れません。
#   Case 1: -shm がロックされていてもスナップショットでき、除外される
#   Case 2: 無変更ならスナップショットは一致する
#   Case 3: DB本体 (.sqlite3) の変更を検出する
#   Case 4: WAL (*-wal) の変更を検出する
#   Case 5: -shm の内容変更は比較に影響しない（除外の範囲）
#   Case 6: DB本体が読み取れない場合は例外で安全に失敗する
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'snapshot_lib.ps1')
$script:Failures = @()
function Check([string]$Name, [bool]$Ok) {
    if ($Ok) { Write-Host "[OK] $Name" } else { Write-Host "[NG] $Name"; $script:Failures += $Name }
}

$Root = Join-Path ([System.IO.Path]::GetTempPath()) ("LivemetrySnapshotTest_" + [guid]::NewGuid().ToString('N'))
$DbDir = Join-Path $Root 'capture_fixed\battle_dataset'
New-Item -ItemType Directory -Path $DbDir -Force | Out-Null
Set-Content -Path (Join-Path $Root 'settings.json') -Value '{"license_key":"dummy"}' -Encoding UTF8
$db = Join-Path $DbDir 'battles.sqlite3'
$wal = "$db-wal"
$shm = "$db-shm"
[System.IO.File]::WriteAllBytes($db, [byte[]](1..100))
[System.IO.File]::WriteAllBytes($wal, [byte[]](1..50))
[System.IO.File]::WriteAllBytes($shm, [byte[]](1..32))

# Case 1: -shm を排他ロックしたままスナップショットできる
$shmLock = [System.IO.File]::Open($shm, 'Open', 'ReadWrite', 'None')
try {
    $snapLocked = Get-FullSnapshot $Root
    Check 'Case1 ロックされた -shm を除外してスナップショットできる' ($snapLocked.Excluded.Count -eq 1 -and $snapLocked.Count -eq 3)
} finally { $shmLock.Dispose() }

$snapA = Get-FullSnapshot $Root
Check 'Case2 無変更なら一致する' ((Get-FullSnapshot $Root).Text -eq $snapA.Text)

# Case 3: DB本体の変更
Add-Content -Path $db -Value 'x' -Encoding ASCII
Check 'Case3 DB本体の変更を検出する' ((Get-FullSnapshot $Root).Text -ne $snapA.Text)
$snapB = Get-FullSnapshot $Root

# Case 4: WALの変更
Add-Content -Path $wal -Value 'y' -Encoding ASCII
Check 'Case4 WALの変更を検出する' ((Get-FullSnapshot $Root).Text -ne $snapB.Text)
$snapC = Get-FullSnapshot $Root

# Case 5: -shm の内容変更は比較に影響しない
[System.IO.File]::WriteAllBytes($shm, [byte[]](9..99))
Check 'Case5 -shm の変更は除外される（比較に影響しない）' ((Get-FullSnapshot $Root).Text -eq $snapC.Text)

# Case 6: DB本体が読めない場合は例外（安全な失敗）
$dbLock = [System.IO.File]::Open($db, 'Open', 'ReadWrite', 'None')
$threw = $false
try { Get-FullSnapshot $Root | Out-Null } catch { $threw = $true }
finally { $dbLock.Dispose() }
Check 'Case6 読めないDB本体は例外で安全に失敗する' $threw

Remove-Item $Root -Recurse -Force -ErrorAction SilentlyContinue
if ($script:Failures.Count -gt 0) { Write-Host 'SNAPSHOT TESTS: FAIL'; exit 1 }
Write-Host 'SNAPSHOT TESTS: PASS'
exit 0
