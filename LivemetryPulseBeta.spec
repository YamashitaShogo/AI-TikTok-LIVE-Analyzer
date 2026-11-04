# -*- mode: python ; coding: utf-8 -*-
# BETA edition spec. Identical to LivemetryPulse.spec except:
#   * the executable / folder are named LivemetryPulseBeta
#   * version_info_beta.txt is used (ProductVersion 1.6.0-beta.1)
#   * beta_edition.flag is bundled, which switches the app to the
#     beta data root (see core/app_edition.py) so it never touches
#     the release build's data.
# Keep the shared parts in sync with LivemetryPulse.spec.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH)
datas = collect_data_files("customtkinter")
datas += collect_data_files("webview")
hiddenimports = []

for package in ("customtkinter", "openai", "httpx", "pydantic", "reportlab", "PIL", "webview", "pyaudiowpatch", "TikTokLive", "TikTokLiveProto"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

for folder_name in ("assets", "images", "icons", "prompts", "config", "data"):
    folder = project_root / folder_name
    if folder.exists():
        datas.append((str(folder), folder_name))

beta_flag = project_root / "beta_edition.flag"
if beta_flag.exists():
    datas.append((str(beta_flag), "."))

for file_name in (".env.example",):
    file_path = project_root / file_name
    if file_path.exists():
        datas.append((str(file_path), "."))

icon_path = project_root / "assets" / "LivemetryPulse.ico"
icon_value = str(icon_path) if icon_path.exists() else None

a = Analysis(
    ["app.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pytest", "matplotlib.tests"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LivemetryPulseBeta",
    version="version_info_beta.txt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=icon_value,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LivemetryPulseBeta",
)
