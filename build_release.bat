@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Livemetry Pulse v1.0.0 Build

echo ==========================================
echo Livemetry Pulse v1.0.0
echo 配布用 One Folder EXE 作成
echo ==========================================
echo.

if not exist "app.py" (
  echo [エラー] app.py がありません。
  pause
  exit /b 1
)

if not exist "version_info.txt" (
  echo [エラー] version_info.txt がありません。
  pause
  exit /b 1
)

if not exist "assets\AI_TikTok_LIVE_Analyzer.ico" (
  echo [エラー] アイコンがありません。
  pause
  exit /b 1
)

python -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo [エラー] PyInstallerの準備に失敗しました。
  pause
  exit /b 1
)

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

python -m PyInstaller --noconfirm --clean "LivemetryPulse.spec"
if errorlevel 1 (
  echo [エラー] ビルドに失敗しました。
  pause
  exit /b 1
)

echo.
echo 完成:
echo %cd%\dist\LivemetryPulse\LivemetryPulse.exe
echo.
pause
