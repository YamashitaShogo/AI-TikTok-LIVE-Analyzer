@echo off
chcp 65001 > nul
title AI TikTok LIVE Analyzer - インストーラー作成

cd /d "%~dp0"

echo ==========================================
echo AI TikTok LIVE Analyzer インストーラー作成
echo ==========================================
echo.

if not exist "dist\AI_TikTok_LIVE_Analyzer.exe" (
    echo [エラー] dist\AI_TikTok_LIVE_Analyzer.exe が見つかりません。
    echo 先に build_exe_fix.bat を実行してください。
    pause
    exit /b 1
)

if not exist "assets\AI_TikTok_LIVE_Analyzer.ico" (
    echo [エラー] アイコンが見つかりません。
    pause
    exit /b 1
)

set "ISCC="

if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)

if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
)

if not defined ISCC (
    echo [エラー] Inno Setup 6 が見つかりません。
    echo Inno Setup 6をインストールしてから再実行してください。
    echo https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

if exist "installer" rmdir /s /q "installer"

echo インストーラーを作成しています...
"%ISCC%" "installer.iss"

if errorlevel 1 (
    echo.
    echo [エラー] インストーラー作成に失敗しました。
    pause
    exit /b 1
)

echo.
echo ==========================================
echo 完成しました。
echo installer\AI_TikTok_LIVE_Analyzer_Setup_v1.0.0.exe
echo ==========================================
echo.
pause
