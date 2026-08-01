# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH)
datas = collect_data_files("customtkinter")
hiddenimports = []

for package in ("customtkinter", "openai", "httpx", "pydantic", "obsws_python", "reportlab", "PIL"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

for folder_name in ("assets", "images", "icons", "prompts", "config"):
    folder = project_root / folder_name
    if folder.exists():
        datas.append((str(folder), folder_name))

for file_name in ("settings.json", ".env.example"):
    file_path = project_root / file_name
    if file_path.exists():
        datas.append((str(file_path), "."))

icon_path = project_root / "assets" / "app.ico"
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
    name="AI-TikTok-LIVE-Analyzer",
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
    name="AI-TikTok-LIVE-Analyzer",
)
