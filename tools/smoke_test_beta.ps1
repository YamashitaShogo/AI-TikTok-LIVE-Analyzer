# Livemetry Pulse Beta — EXE スモークテスト
# ビルド直後のベータEXEを、テスト用LOCALAPPDATAで起動し、
#   ・ベータ専用フォルダに settings.json が生成されること
#   ・テスト用ルート直下に通常版のフォルダを作らないこと
#   ・正常に終了できること
#   ・通常版（実LOCALAPPDATA）のデータが一切変わらないこと
# を確認します。通常版のデータには読み取り（ハッシュ計算）しかしません。
param(
    [string]$ExePath = (Join-Path $PSScriptRoot "..\dist\LivemetryPulseBeta\LivemetryPulseBeta.exe")
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

$ExePath = (Resolve-Path $ExePath).Path
Write-Host "対象EXE: $ExePath"
$NormalData = Join-Path $env:LOCALAPPDATA 'AI-TikTok-LIVE-Analyzer'
$before = Snapshot $NormalData

$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("LivemetryBetaSmoke_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TestRoot | Out-Null
$oldLocal = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = $TestRoot
    $proc = Start-Process -FilePath $ExePath -PassThru
    $betaSettings = Join-Path $TestRoot 'LivemetryPulseBeta\AI-TikTok-LIVE-Analyzer\settings.json'
    $deadline = (Get-Date).AddSeconds(90)
    $started = $false
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) { break }
        if (Test-Path $betaSettings) { $started = $true; break }
        Start-Sleep -Milliseconds 500
        $proc.Refresh()
    }
    Check 'ベータ専用フォルダに settings.json が生成される' $started
    Check 'テスト用ルート直下に通常版フォルダを作らない' (-not (Test-Path (Join-Path $TestRoot 'AI-TikTok-LIVE-Analyzer')))
    if (-not $proc.HasExited) {
        $null = $proc.CloseMainWindow()
        $proc.WaitForExit(30000) | Out-Null
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force; Check '終了できる' $false }
        else { Check '終了できる' $true }
    }
} finally {
    $env:LOCALAPPDATA = $oldLocal
}
$after = Snapshot $NormalData
Check '通常版のデータが不変（settingsハッシュ・ファイル数）' ($before.Count -eq $after.Count -and $before.SettingsHash -eq $after.SettingsHash)
Write-Host "テスト用フォルダ: $TestRoot"
if ($script:Failures.Count -gt 0) { Write-Host 'SMOKE: FAIL'; exit 1 }
Write-Host 'SMOKE: PASS'
exit 0
