@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Livemetry Pulse Beta Build

set BETA_VERSION=1.6.0-beta.1

echo ==========================================
echo Livemetry Pulse Beta v%BETA_VERSION%
echo テスト配布用 One Folder EXE 作成
echo ==========================================
echo.

if not exist "app.py" (
  echo [エラー] app.py がありません。
  pause
  exit /b 1
)

if not exist "version_info_beta.txt" (
  echo [エラー] version_info_beta.txt がありません。
  pause
  exit /b 1
)

if not exist "installer_beta.iss" (
  echo [エラー] installer_beta.iss がありません。
  pause
  exit /b 1
)

if not exist "beta_edition.flag" (
  echo [エラー] beta_edition.flag がありません。
  pause
  exit /b 1
)

if not exist "assets\LivemetryPulse.ico" (
  echo [エラー] アイコンがありません。
  pause
  exit /b 1
)

rem バージョン表記の一致チェック（app_edition / version_info / installer）
findstr /C:"%BETA_VERSION%" core\app_edition.py > nul || (echo [エラー] core\app_edition.py の BETA_VERSION_LABEL が %BETA_VERSION% と一致しません。& pause & exit /b 1)
findstr /C:"%BETA_VERSION%" version_info_beta.txt > nul || (echo [エラー] version_info_beta.txt の表記が %BETA_VERSION% と一致しません。& pause & exit /b 1)
findstr /C:"%BETA_VERSION%" installer_beta.iss > nul || (echo [エラー] installer_beta.iss の MyAppVersion が %BETA_VERSION% と一致しません。& pause & exit /b 1)
echo [OK] バージョン表記は3か所とも %BETA_VERSION% で一致しています。

python -m pip install -r requirements-build.txt
if errorlevel 1 (
  echo [エラー] 依存関係のインストールに失敗しました。
  pause
  exit /b 1
)

if exist "build\LivemetryPulseBeta" rmdir /s /q "build\LivemetryPulseBeta"
if exist "dist\LivemetryPulseBeta" rmdir /s /q "dist\LivemetryPulseBeta"

python -m PyInstaller --noconfirm --clean "LivemetryPulseBeta.spec"
if errorlevel 1 (
  echo [エラー] ビルドに失敗しました。
  pause
  exit /b 1
)

echo.
echo スモークテストを実行します...
powershell -ExecutionPolicy Bypass -File "tools\smoke_test_beta.ps1"
if errorlevel 1 (
  echo [エラー] スモークテストに失敗しました。インストーラーは作成しません。
  pause
  exit /b 1
)

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if defined ISCC (
  "%ISCC%" "installer_beta.iss"
  if errorlevel 1 (
    echo [エラー] インストーラーの作成に失敗しました。
    pause
    exit /b 1
  )
  echo.
  echo 完成:
  echo %cd%\dist\LivemetryPulseBeta\LivemetryPulseBeta.exe
  echo %cd%\installer\LivemetryPulseBeta-Setup-v%BETA_VERSION%.exe
) else (
  echo [情報] Inno Setup 6 の ISCC.exe が見つからないため、インストーラーの作成をスキップしました。
  echo 完成:
  echo %cd%\dist\LivemetryPulseBeta\LivemetryPulseBeta.exe
)
echo.
pause
