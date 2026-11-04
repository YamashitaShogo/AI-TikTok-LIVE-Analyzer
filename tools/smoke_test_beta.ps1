# Livemetry Pulse Beta — EXE スモークテスト
# ビルド直後のベータEXEをテスト用LOCALAPPDATAで起動し、
#   ・ベータ専用フォルダに settings.json が生成されること
#   ・テスト用ルート直下に通常版のフォルダを作らないこと
#   ・ウィンドウ表示後に正常終了できること（ライセンス画面経由を含む）
#   ・通常版（実LOCALAPPDATA）のデータが全ファイル不変であること
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
function Check([string]$Name, [bool]$Ok) {
    if ($Ok) { Log "[OK] $Name" } else { Log "[NG] $Name"; $script:Failures += $Name }
}
function Get-FullSnapshot([string]$Dir) {
    # 全ファイルの 相対パス|サイズ|SHA256 をソートして連結した文字列。
    # 通常版データが「全ファイル不変」かを比較するために使う。
    if (-not (Test-Path $Dir)) { return @{ Text = '<absent>'; Count = -1 } }
    $lines = @()
    foreach ($file in (Get-ChildItem $Dir -Recurse -File -ErrorAction SilentlyContinue)) {
        $rel = $file.FullName.Substring($Dir.Length)
        $hash = (Get-FileHash $file.FullName -Algorithm SHA256).Hash
        $lines += ('{0}|{1}|{2}' -f $rel, $file.Length, $hash)
    }
    $sorted = @($lines | Sort-Object)
    return @{ Text = ($sorted -join "`n"); Count = $sorted.Count }
}

$ExePath = (Resolve-Path $ExePath).Path
$NormalData = Join-Path $env:LOCALAPPDATA 'AI-TikTok-LIVE-Analyzer'
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("LivemetryBetaSmoke_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TestRoot | Out-Null
$script:LogPath = Join-Path $TestRoot 'smoke_diagnostics.log'

Log "対象EXE: $ExePath"
Log "テスト用フォルダ: $TestRoot"
$before = Get-FullSnapshot $NormalData
Log "通常版データ スナップショット: $($before.Count) ファイル"

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
                    if (-not $sent -and $verdict -eq 'PASS') { $verdict = 'CLOSE_REJECTED' }
                }
            } elseif ((Get-Date) -gt $windowDeadline -and -not $everSent -and $verdict -eq 'PASS') {
                $verdict = 'WINDOW_NOT_SHOWN'
            }
            Start-Sleep -Milliseconds 300
        }
        if ($proc.HasExited) { $closedCleanly = $true }
        if (-not $closedCleanly) {
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
    Check '終了できる' $closedCleanly
} finally {
    $env:LOCALAPPDATA = $oldLocal
    # 起動失敗・タイムアウト等で残った場合も、自分が起動したPIDだけは止める
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Log "未終了だったPID $($proc.Id)（自プロセス）を強制終了しました"
    }
}
$after = Get-FullSnapshot $NormalData
Check '通常版のデータが不変（全ファイルのハッシュ比較）' ($before.Text -eq $after.Text)
Log "診断ログ: $script:LogPath"
if ($script:Failures.Count -gt 0) { Write-Host "SMOKE: FAIL ($verdict)"; exit 1 }
Write-Host 'SMOKE: PASS'
exit 0
