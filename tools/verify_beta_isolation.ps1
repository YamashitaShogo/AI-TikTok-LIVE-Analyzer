# Livemetry Pulse Beta — 分離検証（インストール〜アンインストール）
# ベータインストーラーを実際にインストールし、実環境（LOCALAPPDATAの
# 上書きなし）で起動しても、通常版v1.6.0のインストールとデータに
# 一切影響しないことを、比較対象ファイル（SQLiteの-shmを除く）の
# ハッシュ比較で確認します。
#
# 事前ガード（どれか該当したら開始せずに中止します）:
#   ・既存のベータ版がインストール済み（先にアンインストールが必要）
#   ・ベータ版のプロセスが実行中
#   ・通常版のプロセスが実行中（観測中の書き込みで比較が壊れるため。
#     強制終了はしません。通常版を終了してから再実行してください）
# 終了操作は、ウィンドウ（MainWindowHandle）が表示されるまで条件待ち
# してから CloseMainWindow を送ります。診断は
# %TEMP%\LivemetryBetaVerify_diagnostics.log に記録します。
# 注意: ベータのデータフォルダ（%LOCALAPPDATA%\LivemetryPulseBeta）は
# アンインストール後も残ります（テストデータ確認のため）。
param(
    [string]$SetupPath = (Join-Path $PSScriptRoot "..\installer\LivemetryPulseBeta-Setup-v1.6.0-beta.1.exe"),
    [int]$StartupWaitSeconds = 90,
    [int]$WindowWaitSeconds = 90,
    [int]$CloseWaitSeconds = 60
)
$ErrorActionPreference = 'Stop'
$script:Failures = @()
$script:Sw = [System.Diagnostics.Stopwatch]::StartNew()
$script:LogPath = Join-Path $env:TEMP 'LivemetryBetaVerify_diagnostics.log'
Set-Content -Path $script:LogPath -Value '' -Encoding UTF8
function Log([string]$Message) {
    $line = '[{0,7:N1}s] {1}' -f $script:Sw.Elapsed.TotalSeconds, $Message
    Write-Host $line
    Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
}
. (Join-Path $PSScriptRoot 'snapshot_lib.ps1')

function Check([string]$Name, [bool]$Ok) {
    if ($Ok) { Log "[OK] $Name" } else { Log "[NG] $Name"; $script:Failures += $Name }
}

function Close-AppWindow($Proc, [string]$Label) {
    # ウィンドウ表示を条件待ちし、表示されたウィンドウにだけ終了を送る。
    # 戻り値: 'closed' / 'already_exited' / 'window_not_shown' / 'close_timeout'
    $closeDeadline = (Get-Date).AddSeconds($WindowWaitSeconds + $CloseWaitSeconds)
    $windowDeadline = (Get-Date).AddSeconds($WindowWaitSeconds)
    $sentHandles = @{}
    $everSent = $false
    while ((Get-Date) -lt $closeDeadline) {
        if ($Proc.HasExited) { Log "$Label プロセス終了: ExitCode=$($Proc.ExitCode)"; return 'closed' }
        $Proc.Refresh()
        $handle = [intptr]::Zero
        $title = ''
        try { $handle = $Proc.MainWindowHandle; $title = $Proc.MainWindowTitle } catch { }
        if ($handle -ne [intptr]::Zero -and -not $sentHandles.ContainsKey($handle.ToString())) {
            $sentHandles[$handle.ToString()] = $true
            Log "$Label ウィンドウ検出: Handle=$handle Title='$title' — CloseMainWindow を送信します"
            $sent = $false
            try { $sent = $Proc.CloseMainWindow() } catch { Log "$Label CloseMainWindow で例外: $($_.Exception.Message)" }
            Log "$Label CloseMainWindow 戻り値: $sent"
            $everSent = $true
        }
        Start-Sleep -Milliseconds 300
    }
    if ($Proc.HasExited) { Log "$Label プロセス終了: ExitCode=$($Proc.ExitCode)"; return 'closed' }
    if (-not $everSent) { return 'window_not_shown' }
    return 'close_timeout'
}

$NormalData = Join-Path $env:LOCALAPPDATA 'AI-TikTok-LIVE-Analyzer'
$ReleaseApp = Join-Path $env:LOCALAPPDATA 'Programs\Livemetry Pulse'
$BetaApp = Join-Path $env:LOCALAPPDATA 'Programs\Livemetry Pulse Beta'
$BetaExe = Join-Path $BetaApp 'LivemetryPulseBeta.exe'
$BetaSettings = Join-Path $env:LOCALAPPDATA 'LivemetryPulseBeta\AI-TikTok-LIVE-Analyzer\settings.json'

# --- 事前ガード ---
if (Test-Path $BetaExe) {
    Log '中止: 既存のベータ版がインストール済みです。先にベータ版をアンインストールしてから再実行してください。'
    Write-Host 'VERIFY: ABORTED (existing beta installation)'
    exit 1
}
if (Get-Process -Name 'LivemetryPulseBeta' -ErrorAction SilentlyContinue) {
    Log '中止: ベータ版のプロセスが実行中です。終了してから再実行してください。'
    Write-Host 'VERIFY: ABORTED (beta process running)'
    exit 1
}
if (Get-Process -Name 'LivemetryPulse' -ErrorAction SilentlyContinue) {
    Log '中止: 通常版が実行中です。観測データの書き込みで比較が壊れるため、通常版を終了してから再実行してください（強制終了はしません）。'
    Write-Host 'VERIFY: ABORTED (release app running)'
    exit 1
}

$SetupPath = (Resolve-Path $SetupPath).Path
try {
    $snap0 = Get-FullSnapshot $NormalData
} catch {
    Log "中止: 通常版データのスナップショットに失敗しました。データには触れていません。詳細: $($_.Exception.Message)"
    Write-Host 'VERIFY: FAIL (SNAPSHOT_FAILED)'
    exit 1
}
Log "通常版データ スナップショット: 比較対象 $($snap0.Count) ファイル"
if ($snap0.Excluded.Count -gt 0) { Log "比較から除外した -shm ファイル: $($snap0.Excluded -join ', ')" }

Log '--- 1) ベータをサイレントインストール'
$install = Start-Process -FilePath $SetupPath -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
Check 'インストールが成功する' ($install.ExitCode -eq 0)
Check 'ベータEXEがベータ専用フォルダに配置される' (Test-Path $BetaExe)
Check 'フラグファイルがEXEの隣にある' (Test-Path (Join-Path $BetaApp 'beta_edition.flag'))

Log '--- 2) ベータEXEを実環境で起動（LOCALAPPDATAは通常のまま）'
$proc = Start-Process -FilePath $BetaExe -PassThru
Log "起動: PID=$($proc.Id)"
$deadline = (Get-Date).AddSeconds($StartupWaitSeconds)
$started = (Test-Path $BetaSettings)
while (-not $started -and (Get-Date) -lt $deadline) {
    if ($proc.HasExited) { break }
    if (Test-Path $BetaSettings) { $started = $true; break }
    Start-Sleep -Milliseconds 300
    $proc.Refresh()
}
Check 'ベータ専用データフォルダに settings.json が生成される' $started
try { $snap1 = Get-FullSnapshot $NormalData } catch { Log "再スナップショット失敗: $($_.Exception.Message)"; $snap1 = @{ Text = '<failed>'; Count = -1; Excluded = @() } }
if ($snap1.Excluded.Count -gt 0) { Log "比較から除外した -shm ファイル: $($snap1.Excluded -join ', ')" }
Check '起動後も通常版データが不変（-shmを除く比較対象ファイルのハッシュ比較）' ($snap0.Text -eq $snap1.Text)
if (-not $proc.HasExited) {
    $closeResult = Close-AppWindow $proc 'ベータ'
    $exitOk = $false
    if ($proc.HasExited) { try { $exitOk = ($proc.ExitCode -eq 0) } catch { } }
    Check "ベータEXEが終了する（結果: $closeResult / ExitCode=0: $exitOk）" ($closeResult -eq 'closed' -and $exitOk)
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Log "起動したPID $($proc.Id) のみを強制終了しました"
    }
}

Log '--- 3) ベータをサイレントアンインストール'
$uninstaller = Join-Path $BetaApp 'unins000.exe'
Check 'アンインストーラーが存在する' (Test-Path $uninstaller)
if (Test-Path $uninstaller) {
    $un = Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
    Check 'アンインストールが成功する' ($un.ExitCode -eq 0)
    Start-Sleep -Seconds 2
    Check 'ベータのインストールフォルダが削除される' (-not (Test-Path $BetaExe))
}
try { $snap2 = Get-FullSnapshot $NormalData } catch { Log "再スナップショット失敗: $($_.Exception.Message)"; $snap2 = @{ Text = '<failed>'; Count = -1; Excluded = @() } }
if ($snap2.Excluded.Count -gt 0) { Log "比較から除外した -shm ファイル: $($snap2.Excluded -join ', ')" }
Check 'アンインストール後も通常版データが不変（-shmを除く比較対象ファイルのハッシュ比較）' ($snap0.Text -eq $snap2.Text)
if (Test-Path $ReleaseApp) {
    Check '通常版のインストールフォルダが残っている' (Test-Path (Join-Path $ReleaseApp 'LivemetryPulse.exe'))
}
Log "ベータのデータフォルダ（残置・手動削除可）: $(Join-Path $env:LOCALAPPDATA 'LivemetryPulseBeta')"
Log "診断ログ: $script:LogPath"
if ($script:Failures.Count -gt 0) { Write-Host 'VERIFY: FAIL'; exit 1 }
Write-Host 'VERIFY: PASS'
exit 0
