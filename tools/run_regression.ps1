# Livemetry Pulse 回帰テスト実行スクリプト (Windows)
#
# 使い方:
#   cd D:\Projects\AI-TikTok-LIVE-Analyzer
#   powershell -ExecutionPolicy Bypass -File tools\run_regression.ps1
#
# 安全性:
# - 実データには触れません。LOCALAPPDATA を一時フォルダへ差し替えて
#   実行するため、実際の settings.json / 収集DB / Cookie は読み書き
#   されません（テスト自体も一時フォルダ内で完結します）。
# - 依存パッケージはリポジトリ内の .venv-regression にのみ入れます。
# - 終了コード: すべて合格なら 0、失敗があれば 1。

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# --- Python を探す -------------------------------------------------
$Python = $null
foreach ($candidate in @('py', 'python')) {
    try {
        $found = Get-Command $candidate -ErrorAction Stop
        $Python = $found.Source
        break
    } catch { }
}
if (-not $Python) {
    Write-Host 'Python が見つかりません。Python 3.12/3.13 を入れてください。' -ForegroundColor Red
    exit 1
}

# --- 専用 venv（リポジトリ内、実環境には影響しない） ----------------
$Venv = Join-Path $RepoRoot '.venv-regression'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Write-Host 'テスト用 venv を作成しています...'
    & $Python -m venv $Venv
    & $VenvPython -m pip install -q --upgrade pip
    & $VenvPython -m pip install -q customtkinter reportlab Pillow 'TikTokLive==7.0.1' opencv-python-headless numpy
}

# --- 実データを守るため LOCALAPPDATA を一時フォルダへ ---------------
$Sandbox = Join-Path $env:TEMP ('livemetry-regression-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Sandbox | Out-Null
$env:LOCALAPPDATA = $Sandbox
$env:PYTHONPATH = $RepoRoot

# --- 全テストを実行 ---------------------------------------------------
$tests = Get-ChildItem (Join-Path $RepoRoot 'tests') -Filter '*_test.py' | Sort-Object Name
$failed = @()
foreach ($test in $tests) {
    Write-Host ("RUN  {0}" -f $test.Name)
    & $VenvPython $test.FullName
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("PASS {0}" -f $test.Name) -ForegroundColor Green
    } else {
        Write-Host ("FAIL {0}" -f $test.Name) -ForegroundColor Red
        $failed += $test.Name
    }
}

Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host ("すべて合格しました（{0} ファイル）" -f $tests.Count) -ForegroundColor Green
    exit 0
} else {
    Write-Host ("失敗: {0}" -f ($failed -join ', ')) -ForegroundColor Red
    exit 1
}
