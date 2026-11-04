# Livemetry Pulse Beta — EXE スモークテスト
# ビルド直後のベータEXEをテスト用LOCALAPPDATAで起動し、
#   ・ベータ専用フォルダに settings.json が生成されること
#   ・テスト用ルート直下に通常版のフォルダを作らないこと
#   ・ウィンドウ表示後に正常終了できること（ライセンス画面経由を含む）
#   ・通常版（実LOCALAPPDATA）のデータが不変であること
#     （SQLiteの-shmを除く比較対象ファイルのハッシュ比較で確認）
# を確認します。
#
# 終了判定について: 起動直後はウィンドウがまだ無く、CloseMainWindow() は
# 何もしません（戻り値 False）。そのため MainWindowHandle が取得できる
# まで条件待ちし、取得できたウィンドウに対してだけ終了を送ります。
# 診断ログには PID / MainWindowHandle / ウィンドウタイトル /
# CloseMainWindow の戻り値 / 終了コード / 経過時間を記録します。
# 強制終了するのは、このテストが起動したプロセス（PID）だけです。
param(
    [string]$ExePath = (Join-Path $PSScriptRoot "..\dist\LivemetryPulseBeta\LivemetryPulseBeta.exe"),
    [int]$StartupWaitSeconds = 90,
    [int]$WindowWaitSeconds = 90,
    [int]$CloseWaitSeconds = 60
)
$ErrorActionPreference = 'Stop'
$script:Failures = @()
$script:LogPath = $null
$script:Sw = [System.Diagnostics.Stopwatch]::StartNew()
function Log([string]$Message) {
    $line = '[{0,7:N1}s] {1}' -f $script:Sw.Elapsed.TotalSeconds, $Message
    Write-Host $line
    if ($script:LogPath) { Add-Content -Path $script:LogPath -Value $line -Encoding UTF8 }
}
. (Join-Path $PSScriptRoot 'snapshot_lib.ps1')

function Check([string]$Name, [bool]$Ok) {
    if ($Ok) { Log "[OK] $Name" } else { Log "[NG] $Name"; $script:Failures += $Name }
}


$ExePath = (Resolve-Path $ExePath).Path
$NormalData = Join-Path $env:LOCALAPPDATA 'AI-TikTok-LIVE-Analyzer'
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("LivemetryBetaSmoke_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TestRoot | Out-Null
$script:LogPath = Join-Path $TestRoot 'smoke_diagnostics.log'

Log "対象EXE: $ExePath"
Log "テスト用フォルダ: $TestRoot"
try {
    $before = Get-FullSnapshot $NormalData
} catch {
    Log "中止: 通常版データのスナップショットに失敗しました。通常版が実行中の可能性があります。データには触れていません。詳細: $($_.Exception.Message)"
    Write-Host 'SMOKE: FAIL (SNAPSHOT_FAILED)'
    exit 1
}
Log "通常版データ スナップショット: 比較対象 $($before.Count) ファイル"
if ($before.Excluded.Count -gt 0) { Log "比較から除外した -shm ファイル: $($before.Excluded -join ', ')" }

$verdict = 'PASS'
$oldLocal = $env:LOCALAPPDATA
$proc = $null
try {
    $env:LOCALAPPDATA = $TestRoot
    $proc = Start-Process -FilePath $ExePath -PassThru
    Log "起動: PID=$($proc.Id)"
    $betaSettings = Join-Path $TestRoot 'LivemetryPulseBeta\AI-TikTok-LIVE-Analyzer\settings.json'

    # --- Phase 1: 起動（settings.json生成 or プロセス早期終了） ---
    $deadline = (Get-Date).AddSeconds($StartupWaitSeconds)
    $started = $false
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) { break }
        if (Test-Path $betaSettings) { $started = $true; break }
        Start-Sleep -Milliseconds 300
        $proc.Refresh()
    }
    if ($proc.HasExited -and -not $started) {
        $verdict = 'START_FAILED_EARLY_EXIT'
        Log "プロセスが起動直後に終了しました: ExitCode=$($proc.ExitCode)"
    } elseif (-not $started) {
        $verdict = 'START_TIMEOUT'
        Log "制限時間内に settings.json が生成されませんでした"
    }
    Check 'ベータ専用フォルダに settings.json が生成される' $started
    Check 'テスト用ルート直下に通常版フォルダを作らない' (-not (Test-Path (Join-Path $TestRoot 'AI-TikTok-LIVE-Analyzer')))

    # --- Phase 2: ウィンドウを待ってから終了を送る ---
    $closedCleanly = $false
    if ($started -and -not $proc.HasExited) {
        $closeDeadline = (Get-Date).AddSeconds($WindowWaitSeconds + $CloseWaitSeconds)
        $windowDeadline = (Get-Date).AddSeconds($WindowWaitSeconds)
        $sentHandles = @{}
        $sentCount = 0
        $everSent = $false
        $closeAccepted = $false
        while ((Get-Date) -lt $closeDeadline) {
            if ($proc.HasExited) { $closedCleanly = $true; break }
            $proc.Refresh()
            $handle = [intptr]::Zero
            $title = ''
            try { $handle = $proc.MainWindowHandle; $title = $proc.MainWindowTitle } catch { }
            if ($handle -ne [intptr]::Zero) {
                $key = $handle.ToString()
                $shouldSend = -not $sentHandles.ContainsKey($key)
                if (-not $shouldSend -and $sentCount -lt 3 -and (Get-Date) -gt $windowDeadline) { $shouldSend = $true }
                if ($shouldSend) {
                    $sentHandles[$key] = $true
                    $sentCount += 1
                    Log "ウィンドウ検出: Handle=$handle Title='$title' — CloseMainWindow を送信します ($sentCount 回目)"
                    $sent = $false
                    try { $sent = $proc.CloseMainWindow() } catch { Log "CloseMainWindow で例外: $($_.Exception.Message)" }
                    Log "CloseMainWindow 戻り値: $sent"
                    $everSent = $true
                    if ($sent) { $closeAccepted = $true }
                    if (-not $sent -and $verdict -eq 'PASS') { $verdict = 'CLOSE_REJECTED' }
                }
            } elseif ((Get-Date) -gt $windowDeadline -and -not $everSent -and $verdict -eq 'PASS') {
                $verdict = 'WINDOW_NOT_SHOWN'
            }
            Start-Sleep -Milliseconds 300
        }
        if ($proc.HasExited) {
            # 正常終了の条件: 終了要求が受理され、ExitCode=0 で終わったこと
            $exitCode = $null
            try { $exitCode = $proc.ExitCode } catch { }
            Log "終了コード確認: ExitCode=$exitCode / 終了要求の受理=$closeAccepted"
            # ループ内で検出した終了も含め、ここで最終判定を確定する
            $closedCleanly = ($exitCode -eq 0 -and $closeAccepted)
            if ($exitCode -ne 0) { $verdict = 'EXIT_CODE_NONZERO' }
            elseif ($verdict -eq 'PASS') { $verdict = 'EXITED_WITHOUT_CLOSE' }
        }
        if (-not $closedCleanly -and $proc.HasExited) {
            # すでに終了しているので強制終了はしない。判定だけ落とす。
        } elseif (-not $closedCleanly) {
            if (-not $everSent) { $verdict = 'WINDOW_NOT_SHOWN' }
            elseif ($verdict -eq 'PASS') { $verdict = 'CLOSE_TIMEOUT' }
            Log "終了制限時間を超えました: verdict=$verdict"
            # 強制終了するのは自分が起動したPIDだけ
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Log "起動したPID $($proc.Id) のみを強制終了しました"
        } else {
            Log "プロセス終了: ExitCode=$($proc.ExitCode) 経過=$([math]::Round($script:Sw.Elapsed.TotalSeconds, 1))s"
            if ($verdict -eq 'CLOSE_REJECTED') { $verdict = 'PASS' }
        }
    }
    Check '終了できる（終了要求が受理され、ExitCode=0で終了）' $closedCleanly
} finally {
    $env:LOCALAPPDATA = $oldLocal
    # 起動失敗・タイムアウト等で残った場合も、自分が起動したPIDだけは止める
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Log "未終了だったPID $($proc.Id)（自プロセス）を強制終了しました"
    }
}
try {
    $after = Get-FullSnapshot $NormalData
} catch {
    Log "通常版データの再スナップショットに失敗しました: $($_.Exception.Message)"
    Check '通常版のデータが不変（-shmを除く比較対象ファイルのハッシュ比較）' $false
    $after = $null
}
if ($after) {
    if ($after.Excluded.Count -gt 0) { Log "比較から除外した -shm ファイル: $($after.Excluded -join ', ')" }
    Check '通常版のデータが不変（-shmを除く比較対象ファイルのハッシュ比較）' ($before.Text -eq $after.Text)
}
Log "診断ログ: $script:LogPath"
if ($script:Failures.Count -gt 0) { Write-Host "SMOKE: FAIL ($verdict)"; exit 1 }
Write-Host 'SMOKE: PASS'
exit 0
