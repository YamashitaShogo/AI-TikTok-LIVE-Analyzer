# Livemetry Pulse Beta — 分離検証（インストール〜アンインストール）
# ベータインストーラーを実際にインストールし、実環境（LOCALAPPDATAの
# 上書きなし）で起動しても、通常版v1.6.0のインストールとデータに
# 一切影響しないことを確認します。
#   手順: 通常版データのスナップショット → サイレントインストール →
#         ベータEXEを実環境で起動 → 通常版データ不変を確認 → 終了 →
#         サイレントアンインストール → 通常版データ不変を再確認
# 注意: ベータのデータフォルダ（%LOCALAPPDATA%\LivemetryPulseBeta）は
# アンインストール後も残ります（テストデータ確認のため）。不要に
# なったら手動で削除してください。通常版のデータはそこには入りません。
param(
    [string]$SetupPath = (Join-Path $PSScriptRoot "..\installer\LivemetryPulseBeta-Setup-v1.6.0-beta.1.exe")
)
$ErrorActionPreference = 'Stop'
$script:Failures = @()
function Check([string]$Name, [bool]$Ok) {
    if ($Ok) { Write-Host "[OK] $Name" } else { Write-Host "[NG] $Name"; $script:Failures += $Name }
}
function Snapshot([string]$Dir) {
    if (-not (Test-Path $Dir)) { return @{ Count = -1; SettingsHash = '' } }
    $files = @(Get-ChildItem $Dir -Recurse -File -ErrorAction SilentlyContinue)
    $settings = Join-Path $Dir 'settings.json'
    $hash = ''
    if (Test-Path $settings) { $hash = (Get-FileHash $settings -Algorithm SHA256).Hash }
    return @{ Count = $files.Count; SettingsHash = $hash }
}
function SameSnapshot($A, $B) { return ($A.Count -eq $B.Count -and $A.SettingsHash -eq $B.SettingsHash) }

$SetupPath = (Resolve-Path $SetupPath).Path
$NormalData = Join-Path $env:LOCALAPPDATA 'AI-TikTok-LIVE-Analyzer'
$ReleaseApp = Join-Path $env:LOCALAPPDATA 'Programs\Livemetry Pulse'
$BetaApp = Join-Path $env:LOCALAPPDATA 'Programs\Livemetry Pulse Beta'
$BetaExe = Join-Path $BetaApp 'LivemetryPulseBeta.exe'
$BetaSettings = Join-Path $env:LOCALAPPDATA 'LivemetryPulseBeta\AI-TikTok-LIVE-Analyzer\settings.json'

$snap0 = Snapshot $NormalData
Write-Host '--- 1) ベータをサイレントインストール'
$install = Start-Process -FilePath $SetupPath -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
Check 'インストールが成功する' ($install.ExitCode -eq 0)
Check 'ベータEXEがベータ専用フォルダに配置される' (Test-Path $BetaExe)
Check 'フラグファイルがEXEの隣にある' (Test-Path (Join-Path $BetaApp 'beta_edition.flag'))

Write-Host '--- 2) ベータEXEを実環境で起動（LOCALAPPDATAは通常のまま）'
$proc = Start-Process -FilePath $BetaExe -PassThru
$deadline = (Get-Date).AddSeconds(90)
$started = $false
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) { break }
    if (Test-Path $BetaSettings) { $started = $true; break }
    Start-Sleep -Milliseconds 500
    $proc.Refresh()
}
Check 'ベータ専用データフォルダに settings.json が生成される' $started
$snap1 = Snapshot $NormalData
Check '起動後も通常版データが不変' (SameSnapshot $snap0 $snap1)
if (-not $proc.HasExited) {
    $null = $proc.CloseMainWindow()
    $proc.WaitForExit(30000) | Out-Null
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
}
Check 'ベータEXEが終了する' $proc.HasExited

Write-Host '--- 3) ベータをサイレントアンインストール'
$uninstaller = Join-Path $BetaApp 'unins000.exe'
Check 'アンインストーラーが存在する' (Test-Path $uninstaller)
if (Test-Path $uninstaller) {
    $un = Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
    Check 'アンインストールが成功する' ($un.ExitCode -eq 0)
    Start-Sleep -Seconds 2
    Check 'ベータのインストールフォルダが削除される' (-not (Test-Path $BetaExe))
}
$snap2 = Snapshot $NormalData
Check 'アンインストール後も通常版データが不変' (SameSnapshot $snap0 $snap2)
if (Test-Path $ReleaseApp) {
    Check '通常版のインストールフォルダが残っている' (Test-Path (Join-Path $ReleaseApp 'LivemetryPulse.exe'))
}
Write-Host "ベータのデータフォルダ（残置・手動削除可）: $(Join-Path $env:LOCALAPPDATA 'LivemetryPulseBeta')"
if ($script:Failures.Count -gt 0) { Write-Host 'VERIFY: FAIL'; exit 1 }
Write-Host 'VERIFY: PASS'
exit 0
